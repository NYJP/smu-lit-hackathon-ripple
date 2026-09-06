"""Approving proposed wording must never edit the document.

This is the single most important invariant in the project, and the reason
`api/services/patching.py` exists at all. The product's standing promise is
that Ripple reads your documents and never rewrites them: the uploaded file
is the organisation's record of what its policy actually said on a given
date, and a tool that quietly edits it destroys the only copy of that fact.

So an approval writes one `document_patches` row and the reader composes the
overlay at render time. The tests below pin all three halves of that:

  * `document_chunks.content` is byte-identical after Approve,
  * the file on disk is byte-identical after Approve,
  * and no SQL that could have changed either one was ever issued
    (asserted directly against sqlite's statement trace, so the test still
    fails if a future refactor writes the content through some other path).

If one of these fails, do not weaken it. The failure means the product no
longer does what its footer says it does.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from api.db import get_connection
from api.errors import ApiError
from api.services import patching, storage
from api.services import recommendations as recommendation_service

from tests.conftest import login_as
from tests.test_workflow import build_impact

CHUNK_TEXT = "Records are retained for 5 years from the date of collection."
SUGGESTED = "Records are retained for 7 years from the date of collection."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_reviewable_impact(conn, owner_id: str, *, review_status: str = "patch_proposed") -> dict:
    """An impact with proposed wording, sitting where Approve is legal.

    Reuses `test_workflow.build_impact` for the regulation -> ... -> impact
    chain, then adds the recommendation, the conflict span, and a real file
    on disk so "the bytes did not change" is a claim about an actual file.
    """
    ids = build_impact(conn, owner_id, review_status=review_status)
    start = CHUNK_TEXT.index("5 years")
    conn.execute(
        "UPDATE document_chunks SET content = ? WHERE id = ?",
        (CHUNK_TEXT, ids["chunk"]),
    )
    conn.execute(
        "UPDATE impacts SET conflicting_span = ?, conflicting_start = ?, conflicting_end = ? WHERE id = ?",
        ("5 years", start, start + len("5 years"), ids["impact"]),
    )
    ids["recommendation"] = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO recommendations
             (id, impact_id, current_text, suggested_text, rationale,
              requires_human_decision, source_citations, generation_method, created_at)
           VALUES (?, ?, '5 years', '7 years', 'The retention period was extended.',
                   0, '[]', 'model', ?)""",
        (ids["recommendation"], ids["impact"], _now()),
    )

    # A real file, so the byte-identity assertion has something to be about.
    relative = conn.execute(
        "SELECT file_path FROM documents WHERE id = ?", (ids["document"],)
    ).fetchone()["file_path"]
    absolute = Path(storage.absolute_path(relative))
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(CHUNK_TEXT.encode("utf-8"))
    ids["file_path"] = str(absolute)
    conn.commit()
    return ids


def _chunk_content(conn, chunk_id: str) -> str:
    return conn.execute("SELECT content FROM document_chunks WHERE id = ?", (chunk_id,)).fetchone()["content"]


def _digest(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------- the core invariant --

def test_approve_writes_a_patch_and_leaves_the_chunk_and_file_untouched(client, users, conn):
    """Approve -> document_patches row; content and file bytes unchanged."""
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    before_content = _chunk_content(conn, ids["chunk"])
    before_digest = _digest(ids["file_path"])
    assert before_content == CHUNK_TEXT

    login_as(client, priya["id"])
    response = client.post(f"/api/v1/impacts/{ids['impact']}/patch", json={})
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["patch_id"]
    assert body["impact"]["review_status"] == "resolved"

    # The patch exists and carries the approved wording.
    fresh = get_connection()
    try:
        patch = fresh.execute(
            "SELECT * FROM document_patches WHERE id = ?", (body["patch_id"],)
        ).fetchone()
        assert patch["patched_text"] == "7 years"
        assert patch["original_text"] == "5 years"
        assert patch["status"] == "applied"
        assert patch["document_chunk_id"] == ids["chunk"]

        # ...and the document itself did not move.
        assert _chunk_content(fresh, ids["chunk"]) == before_content
    finally:
        fresh.close()
    assert _digest(ids["file_path"]) == before_digest


def test_apply_patch_issues_no_write_against_document_chunks(client, users, conn):
    """Belt and braces: watch the SQL, not just the result.

    Comparing before/after content would still pass if a future change wrote
    the chunk and then wrote it back. This asserts the statement never runs.
    """
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])

    statements: list[str] = []
    tracked = get_connection()
    tracked.set_trace_callback(statements.append)
    try:
        patching.apply_patch(tracked, ids["impact"], "7 years", priya["id"])
        tracked.commit()
    finally:
        tracked.set_trace_callback(None)
        tracked.close()

    writes = [
        sql for sql in statements
        if sql.strip().split(None, 1)[0].upper() in {"UPDATE", "DELETE", "INSERT", "REPLACE"}
    ]
    assert writes, "expected apply_patch to write something"
    for sql in writes:
        assert "document_chunks" not in sql.lower(), f"apply_patch wrote to document_chunks: {sql}"
        assert "documents" not in sql.lower().replace("document_patches", ""), (
            f"apply_patch wrote to documents: {sql}"
        )
    # Exactly two writes: the patch, and the audit record of it.
    assert len(writes) == 2, writes
    assert "document_patches" in writes[0].lower()
    assert "audit_events" in writes[1].lower()


def test_the_reader_can_reconstruct_the_patched_text_without_the_document_changing(client, users, conn):
    """The overlay is renderable: span + text compose back to the new wording."""
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    login_as(client, priya["id"])
    client.post(f"/api/v1/impacts/{ids['impact']}/patch", json={})

    detail = client.get(f"/api/v1/documents/{ids['document']}").json()
    chunk = next(item for item in detail["chunks"] if item["id"] == ids["chunk"])
    assert chunk["content"] == CHUNK_TEXT, "the stored clause must still read as uploaded"
    assert len(chunk["patches"]) == 1

    patch = chunk["patches"][0]
    composed = (
        chunk["content"][: patch["char_start"]]
        + patch["patched_text"]
        + chunk["content"][patch["char_end"] :]
    )
    assert composed == SUGGESTED
    assert detail["document"]["patch_count"] == 1


# --------------------------------------------------------------- the record --

def test_the_whole_journey_lands_in_both_audit_tables(client, users, conn):
    """detected -> assigned -> in review -> patch proposed -> approved -> resolved."""
    priya = users["Priya Menon"]
    alex = next(user for user in users.values() if user["id"] != priya["id"])
    ids = seed_reviewable_impact(conn, priya["id"], review_status="detected")
    impact_id = ids["impact"]
    login_as(client, priya["id"])

    for payload in (
        {"review_status": "awaiting_review", "assigned_to": alex["id"], "note": "Please review."},
        {"review_status": "in_review"},
        {"review_status": "patch_proposed"},
        {"review_status": "awaiting_approval"},
    ):
        response = client.patch(f"/api/v1/impacts/{impact_id}", json=payload)
        assert response.status_code == 200, response.text

    approved = client.post(f"/api/v1/impacts/{impact_id}/patch", json={"note": "Wording agreed."})
    assert approved.status_code == 201, approved.text

    fresh = get_connection()
    try:
        statuses = [
            row["new_status"] for row in fresh.execute(
                "SELECT new_status FROM impact_review_events WHERE impact_id=? ORDER BY changed_at, rowid",
                (impact_id,),
            ).fetchall()
        ]
        assert statuses == [
            "awaiting_review", "in_review", "patch_proposed", "awaiting_approval", "resolved",
        ]

        actions = [
            row["action"] for row in fresh.execute(
                """SELECT action FROM audit_events
                    WHERE (subject_type='impact' AND subject_id=?)
                       OR (subject_type='document_patch'
                           AND subject_id IN (SELECT id FROM document_patches WHERE impact_id=?))
                    ORDER BY created_at, rowid""",
                (impact_id, impact_id),
            ).fetchall()
        ]
        assert actions.count("impact.transition") == 5
        assert "document_patch.applied" in actions

        impact_row = fresh.execute("SELECT * FROM impacts WHERE id=?", (impact_id,)).fetchone()
        assert impact_row["review_status"] == "resolved"
        assert impact_row["resolved_by"] == priya["id"]
        assert impact_row["assigned_to"] == alex["id"]
    finally:
        fresh.close()

    trail = client.get(f"/api/v1/impacts/{impact_id}").json()["audit_trail"]
    applied = next(event for event in trail if event["action"] == "document_patch.applied")
    assert applied["detail"]["document_modified"] is False
    assert applied["actor_name"] == priya["display_name"]


def test_approving_an_edit_records_who_wrote_the_final_words(client, users, conn):
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    login_as(client, priya["id"])

    response = client.post(
        f"/api/v1/impacts/{ids['impact']}/patch",
        json={"text": "seven (7) years", "note": "House style spells the number out."},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["recommendation"]["status"] == "edited"
    assert body["recommendation"]["edited_text"] == "seven (7) years"
    assert body["patch"]["patched_text"] == "seven (7) years"

    fresh = get_connection()
    try:
        assert _chunk_content(fresh, ids["chunk"]) == CHUNK_TEXT
    finally:
        fresh.close()


# ------------------------------------------------------------------ guards --

def test_generating_wording_walks_a_detected_impact_through_review(client, users, conn, monkeypatch):
    """Proposing wording on a fresh finding must not dead-end on the state machine.

    `patch_proposed` is only reachable from `in_review`, so generating on a
    `detected` impact has to pass through it. This was a real 422: the review
    screen's first button failed on every newly detected impact.
    """
    priya = users["Priya Menon"]
    ids = build_impact(conn, priya["id"], review_status="detected")

    def fake_generate(_conn, _impact_id):
        return {"id": "rec", "suggested_text": "7 years"}, __import__(
            "api.services.openai", fromlist=["Usage"]
        ).Usage()

    monkeypatch.setattr(recommendation_service, "generate", fake_generate)
    login_as(client, priya["id"])
    response = client.post(f"/api/v1/impacts/{ids['impact']}/recommendation")
    assert response.status_code == 201, response.text

    fresh = get_connection()
    try:
        assert fresh.execute(
            "SELECT review_status FROM impacts WHERE id=?", (ids["impact"],)
        ).fetchone()["review_status"] == "patch_proposed"
        statuses = [
            row["new_status"] for row in fresh.execute(
                # By rowid, not id: both transitions land in one transaction
                # with identical timestamps, and `id` is a random uuid4.
                "SELECT new_status FROM impact_review_events WHERE impact_id=? ORDER BY changed_at, rowid",
                (ids["impact"],),
            ).fetchall()
        ]
        # Both steps are recorded — the intermediate state is not skipped.
        assert statuses == ["in_review", "patch_proposed"]
    finally:
        fresh.close()


def test_approving_without_proposed_wording_is_refused(client, users, conn):
    """`resolved` must never be reachable without a recorded proposal."""
    priya = users["Priya Menon"]
    ids = build_impact(conn, priya["id"], review_status="in_review")
    login_as(client, priya["id"])

    response = client.post(f"/api/v1/impacts/{ids['impact']}/patch", json={})
    assert response.status_code == 409
    assert "proposed wording" in response.json()["error"]["message"].lower()
    assert not conn.execute(
        "SELECT 1 FROM document_patches WHERE impact_id = ?", (ids["impact"],)
    ).fetchall()


def test_approving_from_a_stage_the_state_machine_refuses_writes_nothing(client, users, conn):
    """The transaction is all-or-nothing: no orphan patch behind a 422."""
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"], review_status="detected")
    login_as(client, priya["id"])

    response = client.post(f"/api/v1/impacts/{ids['impact']}/patch", json={})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_transition"

    fresh = get_connection()
    try:
        assert not fresh.execute(
            "SELECT 1 FROM document_patches WHERE impact_id = ?", (ids["impact"],)
        ).fetchall()
        assert not fresh.execute(
            "SELECT 1 FROM recommendation_decisions WHERE recommendation_id = ?",
            (ids["recommendation"],),
        ).fetchall()
        assert fresh.execute(
            "SELECT review_status FROM impacts WHERE id=?", (ids["impact"],)
        ).fetchone()["review_status"] == "detected"
    finally:
        fresh.close()


def test_a_simulated_change_cannot_produce_a_real_patch(client, users, conn):
    """PRD section 10.4: a hypothetical must never leave a real artefact."""
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    simulation_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO simulations (id, created_by, name, status, created_at, updated_at)
           VALUES (?, ?, 'Retention: 5y -> 7y', 'complete', ?, ?)""",
        (simulation_id, priya["id"], _now(), _now()),
    )
    conn.execute(
        "UPDATE regulatory_changes SET source='simulation', simulation_id=? WHERE id=?",
        (simulation_id, ids["change"]),
    )
    conn.commit()
    login_as(client, priya["id"])

    detail = client.get(f"/api/v1/impacts/{ids['impact']}").json()
    assert detail["capabilities"]["accept_recommendation"] is False
    assert detail["capabilities"]["approve_patch"] is False

    response = client.post(f"/api/v1/impacts/{ids['impact']}/patch", json={})
    assert response.status_code == 409
    assert "promote the simulation" in response.json()["error"]["message"].lower()
    assert not conn.execute(
        "SELECT 1 FROM document_patches WHERE impact_id = ?", (ids["impact"],)
    ).fetchall()


def test_empty_approved_wording_is_refused(client, users, conn):
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    with pytest.raises(ApiError) as excinfo:
        patching.apply_patch(conn, ids["impact"], "   ", priya["id"])
    assert excinfo.value.status_code == 422


def test_two_patches_over_the_same_words_are_refused(client, users, conn):
    """Two overlapping overlays cannot both render, so the second is refused."""
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    patching.apply_patch(conn, ids["impact"], "7 years", priya["id"])
    conn.commit()

    other = build_impact(conn, priya["id"], review_status="in_review")
    start = CHUNK_TEXT.index("5 years")
    conn.execute(
        """UPDATE impacts SET document_chunk_id=?, document_id=?,
                              conflicting_start=?, conflicting_end=? WHERE id=?""",
        (ids["chunk"], ids["document"], start, start + len("5 years"), other["impact"]),
    )
    conn.commit()

    with pytest.raises(ApiError) as excinfo:
        patching.apply_patch(conn, other["impact"], "ten years", priya["id"])
    assert excinfo.value.status_code == 409


def test_reapproving_the_same_impact_replaces_its_own_overlay(client, users, conn):
    """Reopen -> approve again leaves exactly one applied patch, not two."""
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    first = patching.apply_patch(conn, ids["impact"], "7 years", priya["id"])
    second = patching.apply_patch(conn, ids["impact"], "8 years", priya["id"])
    conn.commit()

    rows = {
        row["id"]: row["status"] for row in conn.execute(
            "SELECT id, status FROM document_patches WHERE impact_id=?", (ids["impact"],)
        ).fetchall()
    }
    assert rows[first] == "reverted"
    assert rows[second] == "applied"
    assert patching.patch_for_impact(conn, ids["impact"])["patched_text"] == "8 years"


def test_reverting_reopens_the_impact_and_keeps_the_record(client, users, conn):
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    login_as(client, priya["id"])
    approved = client.post(f"/api/v1/impacts/{ids['impact']}/patch", json={}).json()

    response = client.delete(f"/api/v1/impacts/{ids['impact']}/patch")
    assert response.status_code == 200, response.text
    assert response.json()["impact"]["review_status"] == "in_review"
    assert response.json()["patch"] is None

    fresh = get_connection()
    try:
        row = fresh.execute(
            "SELECT status, reverted_by FROM document_patches WHERE id=?", (approved["patch_id"],)
        ).fetchone()
        assert row["status"] == "reverted"
        assert row["reverted_by"] == priya["id"]
        assert _chunk_content(fresh, ids["chunk"]) == CHUNK_TEXT
    finally:
        fresh.close()


def test_rejecting_after_an_acceptance_withdraws_the_overlay(client, users, conn):
    """Nobody stands behind rejected wording, so the reader must stop showing it."""
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    login_as(client, priya["id"])
    client.post(f"/api/v1/impacts/{ids['impact']}/patch", json={})

    response = client.patch(
        f"/api/v1/recommendations/{ids['recommendation']}",
        json={"status": "rejected", "decision_note": "Wrong section."},
    )
    assert response.status_code == 200, response.text

    fresh = get_connection()
    try:
        assert patching.patch_for_impact(fresh, ids["impact"]) is None
        assert _chunk_content(fresh, ids["chunk"]) == CHUNK_TEXT
    finally:
        fresh.close()


def test_accepting_through_the_recommendations_endpoint_also_writes_a_patch(client, users, conn):
    """The two entry points share one code path; neither may skip the patch."""
    priya = users["Priya Menon"]
    ids = seed_reviewable_impact(conn, priya["id"])
    login_as(client, priya["id"])

    response = client.patch(
        f"/api/v1/recommendations/{ids['recommendation']}", json={"status": "accepted"}
    )
    assert response.status_code == 200, response.text

    fresh = get_connection()
    try:
        patch = patching.patch_for_impact(fresh, ids["impact"])
        assert patch is not None and patch["patched_text"] == "7 years"
        assert _chunk_content(fresh, ids["chunk"]) == CHUNK_TEXT
    finally:
        fresh.close()


def test_span_falls_back_to_the_whole_clause_when_no_conflict_was_recorded():
    """An unlocatable span replaces the passage shown, never a guessed slice."""
    assert patching.resolve_span(CHUNK_TEXT, start=None, end=None) == (0, len(CHUNK_TEXT))
    assert patching.resolve_span(CHUNK_TEXT, start=5, end=2) == (0, len(CHUNK_TEXT))
    assert patching.resolve_span(CHUNK_TEXT, start=0, end=999) == (0, len(CHUNK_TEXT))
    located = patching.resolve_span(CHUNK_TEXT, start=None, end=None, fallback_text="5 years")
    assert CHUNK_TEXT[located[0] : located[1]] == "5 years"
