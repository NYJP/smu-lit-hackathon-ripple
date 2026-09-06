"""The impact review state machine (api/services/workflow.py).

Before this module a resolved impact could be silently pushed back to any
other status with no record of who did it. These tests pin the guard and the
audit writes that PRD section 10.1 rule 4 requires.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from api.errors import ApiError
from api.services import workflow

from tests.conftest import login_as, make_document


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_impact(
    conn,
    owner_id: str,
    *,
    review_status: str = "detected",
    impact_level: str = "high",
    effective_date: str | None = None,
) -> dict:
    """Insert the whole chain an impact needs: regulation → lineage →
    requirement → document → chunk → dependency → change → impact.

    The upload and analysis endpoints would do this for real, but they cost
    model calls; the state machine only cares about the rows.
    """
    ids = {key: uuid.uuid4().hex for key in
           ("regulation", "lineage", "requirement", "chunk", "dependency", "change", "impact")}
    now = _now()
    document_id = make_document(conn, owner_id, "Retention Policy")
    ids["document"] = document_id

    conn.execute(
        """INSERT INTO regulations (id, title, document_kind, file_path, file_name, status, created_at)
           VALUES (?, 'Rules', 'primary', 'regulations/r.pdf', 'r.pdf', 'ready', ?)""",
        (ids["regulation"], now),
    )
    conn.execute(
        """INSERT INTO requirement_lineages (id, public_ref, subject, origin_regulation_id, created_at)
           VALUES (?, ?, 'record_retention', ?, ?)""",
        (ids["lineage"], f"REQ-{ids['lineage'][:3]}", ids["regulation"], now),
    )
    conn.execute(
        """INSERT INTO regulatory_requirements
           (id, lineage_id, regulation_id, requirement_text, requirement_type, subject, is_current, created_at)
           VALUES (?, ?, ?, 'Retain records for 5 years.', 'duration', 'record_retention', 1, ?)""",
        (ids["requirement"], ids["lineage"], ids["regulation"], now),
    )
    conn.execute(
        "UPDATE requirement_lineages SET current_version_id = ? WHERE id = ?",
        (ids["requirement"], ids["lineage"]),
    )
    conn.execute(
        """INSERT INTO document_chunks (id, document_id, ordinal, content, chunk_type, created_at)
           VALUES (?, ?, 0, 'Records are retained for 5 years.', 'paragraph', ?)""",
        (ids["chunk"], document_id, now),
    )
    conn.execute(
        """INSERT INTO dependencies
           (id, lineage_id, document_chunk_id, document_id, relationship_type, confidence, rationale, status, created_at)
           VALUES (?, ?, ?, ?, 'restates', 0.95, 'Restates the retention period.', 'active', ?)""",
        (ids["dependency"], ids["lineage"], ids["chunk"], document_id, now),
    )
    conn.execute(
        """INSERT INTO regulatory_changes
           (id, lineage_id, source, detected_from_regulation_id, previous_requirement_id,
            change_type, old_value, new_value, summary, effective_date, analysis_status, created_at)
           VALUES (?, ?, 'amendment', ?, ?, 'duration', '5 years', '7 years',
                   'Retention: 5 years to 7 years', ?, 'complete', ?)""",
        (ids["change"], ids["lineage"], ids["regulation"], ids["requirement"], effective_date, now),
    )
    conn.execute(
        """INSERT INTO impacts
           (id, regulatory_change_id, dependency_id, document_id, document_chunk_id,
            impact_level, confidence, reason, review_status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 0.95, 'Contains the superseded value.', ?, ?)""",
        (ids["impact"], ids["change"], ids["dependency"], document_id, ids["chunk"],
         impact_level, review_status, now),
    )
    conn.commit()
    return ids


# ------------------------------------------------------------ pure guards --

def test_terminal_and_open_sets_partition_every_status():
    """Fail if a new status is added without deciding whether it is open."""
    assert set(workflow.OPEN_STATUSES) | workflow.TERMINAL_STATUSES == set(workflow.STATUSES)
    assert not set(workflow.OPEN_STATUSES) & workflow.TERMINAL_STATUSES


def test_every_status_has_a_label_and_a_transition_entry():
    for status in workflow.STATUSES:
        assert status in workflow.STATUS_LABELS
        assert status in workflow.ALLOWED_TRANSITIONS


def test_every_transition_target_is_a_real_status():
    for source, targets in workflow.ALLOWED_TRANSITIONS.items():
        for target in targets:
            assert target in workflow.STATUSES, f"{source} -> {target}"


def test_superseded_is_a_dead_end():
    """A newer change owns the question now; the work belongs on that change."""
    assert workflow.ALLOWED_TRANSITIONS["superseded"] == frozenset()


def test_resolved_and_dismissed_can_be_reopened():
    """A reviewer who closed the wrong row must be able to undo it."""
    assert workflow.can_transition("resolved", "in_review")
    assert workflow.can_transition("dismissed", "in_review")


def test_detected_cannot_jump_straight_to_resolved():
    """Resolving is a decision, so it must pass through a review stage."""
    assert not workflow.can_transition("detected", "resolved")


# --------------------------------------------------------- the transition --

def test_legal_transition_writes_status_audit_and_notification(client, conn, users):
    ids = build_impact(conn, users["Priya Menon"]["id"])
    actor = users["Alex Tan"]["id"]

    workflow.transition(conn, ids["impact"], "in_review", actor, note="Taking a look.")
    conn.commit()

    row = conn.execute("SELECT * FROM impacts WHERE id = ?", (ids["impact"],)).fetchone()
    assert row["review_status"] == "in_review"
    assert row["updated_at"] is not None

    event = conn.execute(
        "SELECT * FROM impact_review_events WHERE impact_id = ?", (ids["impact"],)
    ).fetchone()
    assert (event["previous_status"], event["new_status"]) == ("detected", "in_review")
    assert event["changed_by"] == actor

    audit = conn.execute(
        "SELECT * FROM audit_events WHERE subject_id = ? AND action = 'impact.transition'",
        (ids["impact"],),
    ).fetchone()
    assert audit["actor_id"] == actor

    # Priya owns the document, so she hears about it; Alex made the change and
    # must not be told about his own action.
    recipients = {
        r["user_id"] for r in conn.execute(
            "SELECT user_id FROM notifications WHERE subject_id = ?", (ids["impact"],)
        )
    }
    assert users["Priya Menon"]["id"] in recipients
    assert actor not in recipients


def test_illegal_transition_is_refused_and_changes_nothing(client, conn, users):
    ids = build_impact(conn, users["Priya Menon"]["id"])

    with pytest.raises(ApiError) as excinfo:
        workflow.transition(conn, ids["impact"], "resolved", users["Priya Menon"]["id"])
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "invalid_transition"
    assert "resolved" not in excinfo.value.details["allowed"]

    row = conn.execute("SELECT review_status FROM impacts WHERE id = ?", (ids["impact"],)).fetchone()
    assert row["review_status"] == "detected"
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM impact_review_events WHERE impact_id = ?", (ids["impact"],)
    ).fetchone()["n"] == 0


def test_terminal_transition_records_who_resolved_it(client, conn, users):
    ids = build_impact(conn, users["Priya Menon"]["id"], review_status="patch_proposed")
    actor = users["Sam Rahim"]["id"]

    workflow.transition(conn, ids["impact"], "resolved", actor)
    conn.commit()

    row = conn.execute("SELECT * FROM impacts WHERE id = ?", (ids["impact"],)).fetchone()
    assert row["review_status"] == "resolved"
    assert row["resolved_by"] == actor
    assert row["resolved_at"] is not None


def test_reopening_clears_the_resolution_record(client, conn, users):
    """Fail if a reopened impact still claims it was resolved by someone."""
    ids = build_impact(conn, users["Priya Menon"]["id"], review_status="resolved")
    workflow.transition(conn, ids["impact"], "in_review", users["Alex Tan"]["id"])
    conn.commit()

    row = conn.execute("SELECT * FROM impacts WHERE id = ?", (ids["impact"],)).fetchone()
    assert row["resolved_by"] is None
    assert row["resolved_at"] is None


def test_same_status_still_applies_assignment_without_an_audit_event(client, conn, users):
    """Reassigning must not fabricate a status change in the history."""
    ids = build_impact(conn, users["Priya Menon"]["id"])
    assignee = users["Sam Rahim"]["id"]

    workflow.transition(
        conn, ids["impact"], "detected", users["Priya Menon"]["id"],
        assigned_to=assignee, due_date="2026-04-01",
    )
    conn.commit()

    row = conn.execute("SELECT * FROM impacts WHERE id = ?", (ids["impact"],)).fetchone()
    assert row["assigned_to"] == assignee
    assert row["due_date"] == "2026-04-01"
    assert row["review_status"] == "detected"
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM impact_review_events WHERE impact_id = ?", (ids["impact"],)
    ).fetchone()["n"] == 0
    # The assignee is told, because being handed work is the notifiable event.
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND event_type = 'impact.assigned'",
        (assignee,),
    ).fetchone()["n"] == 1


def test_unknown_impact_is_404(client, conn, users):
    with pytest.raises(ApiError) as excinfo:
        workflow.transition(conn, "does-not-exist", "in_review", users["Alex Tan"]["id"])
    assert excinfo.value.status_code == 404


def test_unknown_status_is_422(client, conn, users):
    ids = build_impact(conn, users["Priya Menon"]["id"])
    with pytest.raises(ApiError) as excinfo:
        workflow.transition(conn, ids["impact"], "closed_wontfix", users["Alex Tan"]["id"])
    assert excinfo.value.status_code == 422


def test_supersede_closes_open_impacts_on_the_lineage_only(client, conn, users):
    open_ids = build_impact(conn, users["Priya Menon"]["id"])
    closed_ids = build_impact(conn, users["Alex Tan"]["id"], review_status="resolved")

    superseded = workflow.supersede_open_impacts(conn, open_ids["lineage"], users["Alex Tan"]["id"])
    conn.commit()

    assert superseded == 1
    assert conn.execute(
        "SELECT review_status FROM impacts WHERE id = ?", (open_ids["impact"],)
    ).fetchone()["review_status"] == "superseded"
    # A different lineage, and an already-closed impact, are both untouched.
    assert conn.execute(
        "SELECT review_status FROM impacts WHERE id = ?", (closed_ids["impact"],)
    ).fetchone()["review_status"] == "resolved"


# ------------------------------------------------------------ the API edge --

def test_patch_endpoint_refuses_an_illegal_transition(client, conn, users):
    ids = build_impact(conn, users["Priya Menon"]["id"])
    login_as(client, users["Priya Menon"]["id"])

    response = client.patch(f"/api/v1/impacts/{ids['impact']}", json={"review_status": "resolved"})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_transition"


def test_patch_endpoint_reports_allowed_transitions_and_severity(client, conn, users):
    ids = build_impact(conn, users["Priya Menon"]["id"])
    login_as(client, users["Priya Menon"]["id"])

    response = client.patch(f"/api/v1/impacts/{ids['impact']}", json={"review_status": "in_review"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["impact"]["review_status"] == "in_review"
    assert body["impact"]["review_status_label"] == "In review"
    # No effective date on this change, so a stored 'high' stays 'high'.
    assert body["impact"]["severity"] == "high"
    assert body["impact"]["impact_level"] == "high"
    assert "resolved" in body["capabilities"]["allowed_transitions"]


def test_an_imminent_deadline_surfaces_as_critical_through_the_api(client, conn, users):
    """The stored level is untouched; only the displayed severity escalates."""
    soon = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
    ids = build_impact(conn, users["Priya Menon"]["id"], effective_date=soon)
    login_as(client, users["Priya Menon"]["id"])

    response = client.get(f"/api/v1/impacts/{ids['impact']}")

    assert response.status_code == 200, response.text
    impact = response.json()["impact"]
    assert impact["severity"] == "critical"
    assert impact["impact_level"] == "high"
