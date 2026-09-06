"""Append-only recommendation decisions with a current-state projection."""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import get_db
from api.services import recommendations as recommendation_service

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


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
               WHERE d.recommendation_id=? ORDER BY d.decided_at, d.rowid""",
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
    # The whole decision — the append-only decision row, the patch an
    # acceptance produces, and the impact's transition — lives in
    # services/recommendations.decide() so that POST /impacts/{id}/patch,
    # which the review screen calls, cannot drift from this endpoint.
    result = recommendation_service.decide(
        conn,
        recommendation_id,
        status=payload.status,
        actor_id=user["id"],
        edited_text=payload.edited_text,
        decision_note=payload.decision_note,
    )
    if result["changed"]:
        conn.commit()
    return _response(conn, recommendation_id)
