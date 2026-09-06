"""The impact review state machine, plus the audit and notification writes
that must happen with every transition.

Before this module every status column in the codebase was set ad hoc:
`PATCH /impacts/{id}` accepted any of the four legal values from any current
value, so a resolved impact could silently become detected again with no
record of who did it or why. PRD section 10.1 rule 4 is explicit that every
state change is "a deliberate act by a named person at a recorded time", and
that is only enforceable if one function owns the write.

Three separate dimensions, deliberately never merged:

    severity        how bad could this be      -> services/severity.py
    confidence      how sure is the evidence   -> impacts.confidence
    review status   where is it in the queue   -> here

Convention note: like every other service here, `transition` does NOT commit.
The router owns the transaction boundary so a transition and the write that
prompted it (a recommendation decision, a patch) land atomically or not at all.
"""

from __future__ import annotations

import json
from api.sqlite_driver import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from api.errors import ApiError

# Every legal value of `impacts.review_status`, matching the CHECK constraint
# in migration 008. Kept in workflow order for display.
STATUSES: tuple[str, ...] = (
    "detected",
    "awaiting_review",
    "in_review",
    "needs_analysis",
    "patch_proposed",
    "awaiting_approval",
    "resolved",
    "dismissed",
    "superseded",
)

# Nothing further is expected of these.
TERMINAL_STATUSES: frozenset[str] = frozenset({"resolved", "dismissed", "superseded"})

# Still needs a person. This is the set that drives "action required" counts,
# the graph's affected states, and `open_impact_count` on the documents list.
OPEN_STATUSES: tuple[str, ...] = tuple(s for s in STATUSES if s not in TERMINAL_STATUSES)

# `resolved` and `dismissed` remain reopenable — a reviewer who closed the
# wrong row must be able to undo it, and the audit trail keeps both acts.
# `superseded` does not reopen: a newer change replaced this finding, so the
# work belongs on that change's impact, not this one.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "detected": frozenset({"awaiting_review", "in_review", "needs_analysis", "dismissed", "superseded"}),
    "awaiting_review": frozenset({"in_review", "needs_analysis", "dismissed", "superseded"}),
    "in_review": frozenset(
        {"patch_proposed", "awaiting_approval", "needs_analysis", "awaiting_review", "resolved", "dismissed", "superseded"}
    ),
    "needs_analysis": frozenset({"in_review", "awaiting_review", "dismissed", "superseded"}),
    "patch_proposed": frozenset({"awaiting_approval", "in_review", "resolved", "dismissed", "superseded"}),
    "awaiting_approval": frozenset({"resolved", "patch_proposed", "in_review", "dismissed", "superseded"}),
    "resolved": frozenset({"in_review", "superseded"}),
    "dismissed": frozenset({"in_review", "superseded"}),
    "superseded": frozenset(),
}

# Human-readable, for the UI and for error messages. Cautious register per
# PRD section 10.1 rule 5 — nothing here asserts non-compliance as fact.
STATUS_LABELS: dict[str, str] = {
    "detected": "Detected",
    "awaiting_review": "Awaiting review",
    "in_review": "In review",
    "needs_analysis": "Needs more analysis",
    "patch_proposed": "Proposed wording ready",
    "awaiting_approval": "Awaiting approval",
    "resolved": "Resolved",
    "dismissed": "Dismissed",
    "superseded": "Superseded",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status_placeholders(statuses: Iterable[str]) -> tuple[str, list[str]]:
    """`(placeholder_sql, values)` for an `IN (...)` over a status set."""
    values = list(statuses)
    return ",".join("?" * len(values)) if values else "NULL", values


def open_status_sql(column: str = "review_status") -> tuple[str, list[str]]:
    """`(sql_fragment, values)` matching any status that still needs a person."""
    placeholders, values = status_placeholders(OPEN_STATUSES)
    return f"{column} IN ({placeholders})", values


def can_transition(current: str, new: str) -> bool:
    return new in ALLOWED_TRANSITIONS.get(current, frozenset())


def record_audit(
    conn: sqlite3.Connection,
    *,
    actor_id: str | None,
    action: str,
    subject_type: str,
    subject_id: str,
    detail: dict[str, Any] | None = None,
) -> str:
    """Append one `audit_events` row. Does not commit."""
    event_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO audit_events (id, actor_id, action, subject_type, subject_id, detail_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (event_id, actor_id, action, subject_type, subject_id, json.dumps(detail) if detail else None, _now()),
    )
    return event_id


def notify(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    title: str,
    body: str | None = None,
) -> str | None:
    """Queue one notification. Does not commit. Returns None if `user_id` is falsy."""
    if not user_id:
        return None
    notification_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO notifications (id, user_id, event_type, subject_type, subject_id, title, body, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (notification_id, user_id, event_type, subject_type, subject_id, title, body, _now()),
    )
    return notification_id


def stakeholders(conn: sqlite3.Connection, impact_id: str, *, exclude: str | None = None) -> list[str]:
    """Everyone who should hear about a change to this impact.

    The document owner, its assignee, and any tagged collaborator. Deliberately
    not "every admin" — under the all-admin build that would be everyone, which
    is the fastest way to make notifications worthless.
    """
    rows = conn.execute(
        """SELECT DISTINCT user_id FROM (
               SELECT d.owner_id AS user_id
                 FROM impacts i JOIN documents d ON d.id = i.document_id
                WHERE i.id = :impact_id
               UNION
               SELECT i.assigned_to FROM impacts i WHERE i.id = :impact_id
               UNION
               SELECT dc.user_id
                 FROM impacts i JOIN document_collaborators dc ON dc.document_id = i.document_id
                WHERE i.id = :impact_id
           ) WHERE user_id IS NOT NULL""",
        {"impact_id": impact_id},
    ).fetchall()
    return [row["user_id"] for row in rows if row["user_id"] != exclude]


def transition(
    conn: sqlite3.Connection,
    impact_id: str,
    new_status: str,
    actor_id: str,
    *,
    note: str | None = None,
    assigned_to: str | None = None,
    due_date: str | None = None,
    notify_stakeholders: bool = True,
) -> sqlite3.Row:
    """Move an impact to `new_status`, recording who and when.

    Writes, in order: the impact row, an `impact_review_events` row (the
    existing narrow audit table, kept authoritative), an `audit_events` row,
    and one notification per stakeholder. Raises 404 for an unknown impact and
    422 for a transition the state machine forbids.

    Passing the current status is a no-op for the status itself but still
    applies `assigned_to` / `due_date`, so "reassign without moving stage" works.
    """
    if new_status not in STATUSES:
        raise ApiError(422, "validation_error", f"Unknown review status '{new_status}'.")

    current = conn.execute(
        "SELECT id, review_status, assigned_to, due_date, document_id FROM impacts WHERE id = ?",
        (impact_id,),
    ).fetchone()
    if current is None:
        raise ApiError(404, "not_found", "Impact not found.")

    previous_status = current["review_status"]
    status_changed = previous_status != new_status
    if status_changed and not can_transition(previous_status, new_status):
        allowed = sorted(ALLOWED_TRANSITIONS.get(previous_status, frozenset()))
        raise ApiError(
            422,
            "invalid_transition",
            f"Cannot move an impact from '{STATUS_LABELS.get(previous_status, previous_status)}' "
            f"to '{STATUS_LABELS.get(new_status, new_status)}'.",
            {"current_status": previous_status, "requested_status": new_status, "allowed": allowed},
        )

    now = _now()
    terminal = new_status in {"resolved", "dismissed"}
    conn.execute(
        """UPDATE impacts
              SET review_status = ?,
                  assigned_to   = COALESCE(?, assigned_to),
                  due_date      = COALESCE(?, due_date),
                  resolved_by   = CASE WHEN ? THEN ? ELSE NULL END,
                  resolved_at   = CASE WHEN ? THEN ? ELSE NULL END,
                  updated_at    = ?
            WHERE id = ?""",
        (new_status, assigned_to, due_date, terminal, actor_id, terminal, now, now, impact_id),
    )

    if status_changed:
        conn.execute(
            """INSERT INTO impact_review_events (id, impact_id, previous_status, new_status, changed_by, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, impact_id, previous_status, new_status, actor_id, now),
        )

    record_audit(
        conn,
        actor_id=actor_id,
        action="impact.transition" if status_changed else "impact.update",
        subject_type="impact",
        subject_id=impact_id,
        detail={
            "previous_status": previous_status,
            "new_status": new_status,
            "note": note,
            "assigned_to": assigned_to,
            "due_date": due_date,
        },
    )

    if assigned_to and assigned_to != actor_id:
        notify(
            conn,
            user_id=assigned_to,
            event_type="impact.assigned",
            subject_type="impact",
            subject_id=impact_id,
            title="A review was assigned to you",
            body=note,
        )

    if notify_stakeholders and status_changed:
        for user_id in stakeholders(conn, impact_id, exclude=actor_id):
            notify(
                conn,
                user_id=user_id,
                event_type="impact.status_changed",
                subject_type="impact",
                subject_id=impact_id,
                title=f"Review status is now {STATUS_LABELS.get(new_status, new_status).lower()}",
                body=note,
            )

    return conn.execute("SELECT * FROM impacts WHERE id = ?", (impact_id,)).fetchone()


def supersede_open_impacts(conn: sqlite3.Connection, lineage_id: str, actor_id: str | None = None) -> int:
    """Mark still-open impacts on `lineage_id` superseded.

    Called when a newer change lands on the same requirement lineage: the old
    finding is not wrong, it is simply no longer the current question. Returns
    the number superseded. Does not commit.
    """
    placeholders, values = status_placeholders(OPEN_STATUSES)
    rows = conn.execute(
        f"""SELECT i.id FROM impacts i
              JOIN regulatory_changes c ON c.id = i.regulatory_change_id
             WHERE c.lineage_id = ? AND i.review_status IN ({placeholders})""",
        (lineage_id, *values),
    ).fetchall()
    for row in rows:
        transition(conn, row["id"], "superseded", actor_id or "", notify_stakeholders=False)
    return len(rows)
