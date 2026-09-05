"""Impacts (section 9.6). Not built yet — arrives with the impact engine
wave (PRD build order step 7)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from pydantic import BaseModel
from typing import Literal
from api.auth import get_current_user
from api.db import get_db
from api import access
from api.errors import ApiError

router = APIRouter(prefix="/impacts", tags=["impacts"])

_WAVE = "the impact engine wave (build order step 7)"


@router.get("/{impact_id}")
class ImpactPatch(BaseModel):
    review_status: Literal["open", "in_review", "resolved", "dismissed"]

@router.get("")
def list_impacts(conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    visible = access.visible_document_ids(conn, user)
    rows = conn.execute("SELECT i.*, d.name AS document_name FROM impacts i JOIN documents d ON d.id=i.document_id WHERE i.document_id IN ({}) ORDER BY i.created_at DESC".format(",".join("?" * len(visible)) if visible else "NULL"), list(visible)).fetchall()
    return {"items": [dict(row) for row in rows]}

@router.get("/{impact_id}")
def get_impact(impact_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    row = conn.execute("SELECT * FROM impacts WHERE id = ?", (impact_id,)).fetchone()
    if row is None or not access.is_document_visible(conn, user, row["document_id"]): raise ApiError(404, "not_found", "Impact not found.")
    return dict(row)


@router.patch("/{impact_id}")
def patch_impact(impact_id: str, payload: ImpactPatch, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    row = get_impact(impact_id, conn, user); access.require_document_write(conn, user, row["document_id"])
    conn.execute("UPDATE impacts SET review_status = ?, resolved_by = CASE WHEN ? IN ('resolved','dismissed') THEN ? ELSE resolved_by END, resolved_at = CASE WHEN ? IN ('resolved','dismissed') THEN datetime('now') ELSE resolved_at END WHERE id = ?", (payload.review_status, payload.review_status, user["id"], payload.review_status, impact_id)); conn.commit()
    return dict(conn.execute("SELECT * FROM impacts WHERE id = ?", (impact_id,)).fetchone())


@router.post("/{impact_id}/recommendation", status_code=201)
def generate_recommendation(impact_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented("the recommendations wave (build order step 11)")
