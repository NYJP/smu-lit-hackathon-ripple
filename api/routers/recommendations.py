"""Append-only recommendation decisions with a current-state projection."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecommendationPatch(BaseModel):
    status: Literal["accepted", "rejected", "edited"]
    edited_text: str | None = None
    decision_note: str | None = None


def _response(conn: sqlite3.Connection, recommendation_id: str) -> dict:
    row = conn.execute(
        """SELECT r.*, u.display_name AS decided_by_name
           FROM recommendations r LEFT JOIN users u ON u.id=r.decided_by
           WHERE r.id=?""",
        (recommendation_id,),
    ).fetchone()
    result = dict(row)
    result["source_citations"] = json.loads(result["source_citations"] or "[]")
    result["decision_history"] = [
        dict(item) for item in conn.execute(
            """SELECT d.*, u.display_name AS decided_by_name
               FROM recommendation_decisions d JOIN users u ON u.id=d.decided_by
               WHERE d.recommendation_id=? ORDER BY d.decided_at, d.id""",
            (recommendation_id,),
        ).fetchall()
    ]
    return result


@router.patch("/{recommendation_id}")
def patch_recommendation(
    recommendation_id: str,
    payload: RecommendationPatch,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    row = conn.execute(
        """SELECT r.*, i.id AS impact_id, i.review_status, c.source
           FROM recommendations r
           JOIN impacts i ON i.id=r.impact_id
           JOIN regulatory_changes c ON c.id=i.regulatory_change_id
           WHERE r.id=?""",
        (recommendation_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Recommendation not found.")
    if row["source"] == "simulation" and payload.status == "accepted":
        raise ApiError(409, "conflict", "Promote the simulation before accepting this recommendation.")
    edited_text = payload.edited_text.strip() if payload.edited_text else None
    decision_note = payload.decision_note.strip() if payload.decision_note else None
    if payload.status == "edited" and not edited_text:
        raise ApiError(422, "validation_error", "edited_text is required when marking a recommendation edited.")
    if (
        row["status"] == payload.status
        and (row["edited_text"] or None) == edited_text
        and (row["decision_note"] or None) == decision_note
        and row["decided_by"] == user["id"]
    ):
        return _response(conn, recommendation_id)

    now = _now()
    conn.execute(
        """INSERT INTO recommendation_decisions
           (id, recommendation_id, status, edited_text, decision_note, decided_by, decided_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (uuid.uuid4().hex, recommendation_id, payload.status, edited_text, decision_note, user["id"], now),
    )
    conn.execute(
        """UPDATE recommendations
           SET status=?, edited_text=?, decision_note=?, decided_by=?, decided_at=?
           WHERE id=?""",
        (payload.status, edited_text, decision_note, user["id"], now, recommendation_id),
    )
    next_review_status = "resolved" if payload.status in {"accepted", "edited"} else "in_review"
    if row["review_status"] != next_review_status:
        conn.execute(
            """INSERT INTO impact_review_events
               (id, impact_id, previous_status, new_status, changed_by, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, row["impact_id"], row["review_status"], next_review_status, user["id"], now),
        )
        conn.execute(
            """UPDATE impacts SET review_status=?, resolved_by=?, resolved_at=? WHERE id=?""",
            (
                next_review_status,
                user["id"] if next_review_status == "resolved" else None,
                now if next_review_status == "resolved" else None,
                row["impact_id"],
            ),
        )
    conn.commit()
    return _response(conn, recommendation_id)
