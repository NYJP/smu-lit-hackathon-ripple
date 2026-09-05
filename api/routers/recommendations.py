"""Recommendation decisions for reviewed impacts."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

class RecommendationPatch(BaseModel):
    status: Literal["accepted", "rejected", "edited"]
    edited_text: str | None = None
    decision_note: str | None = None

@router.patch("/{recommendation_id}")
def patch_recommendation(recommendation_id: str, payload: RecommendationPatch, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    row = conn.execute("SELECT r.*, i.document_id, c.source FROM recommendations r JOIN impacts i ON i.id=r.impact_id JOIN regulatory_changes c ON c.id=i.regulatory_change_id WHERE r.id=?", (recommendation_id,)).fetchone()
    if row is None or not access.is_document_visible(conn, user, row["document_id"]):
        raise ApiError(404, "not_found", "Recommendation not found.")
    access.require_document_write(conn, user, row["document_id"])
    if row["source"] == "simulation" and payload.status == "accepted":
        raise ApiError(409, "conflict", "A simulated recommendation must be promoted before it can be accepted.")
    if payload.status == "edited" and not payload.edited_text:
        raise ApiError(422, "validation_error", "edited_text is required when marking a recommendation edited.")
    conn.execute("UPDATE recommendations SET status=?, edited_text=?, decision_note=?, decided_by=?, decided_at=? WHERE id=?", (payload.status, payload.edited_text, payload.decision_note, user["id"], datetime.now(timezone.utc).isoformat(), recommendation_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM recommendations WHERE id=?", (recommendation_id,)).fetchone())
