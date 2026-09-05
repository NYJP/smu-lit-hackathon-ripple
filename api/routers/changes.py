"""Changes, impacts, recommendations feed (section 9.6). Not built yet —
arrives with the impact engine and amendment-detection wave (PRD build
order steps 7 and 9)."""

from __future__ import annotations

import sqlite3
from fastapi import Query

from fastapi import APIRouter, Depends

from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import impact

router = APIRouter(prefix="/changes", tags=["changes"])

_WAVE = "the impact engine and amendment-detection wave (build order steps 7 and 9)"


@router.get("")
def list_changes(conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user), include_simulated: bool = False):
    rows = conn.execute("SELECT * FROM regulatory_changes WHERE (? OR simulation_id IS NULL) ORDER BY created_at DESC", (int(include_simulated),)).fetchall()
    visible = access.visible_document_ids(conn, user)
    items = []
    for row in rows:
        count = conn.execute("SELECT COUNT(*) AS n FROM impacts WHERE regulatory_change_id = ? AND document_id IN ({})".format(",".join("?" * len(visible)) if visible else "NULL"), [row["id"], *visible]).fetchone()["n"]
        if user["role"] == "admin" or count:
            item = dict(row); item["impact_count"] = count; items.append(item)
    return {"items": items}


@router.get("/{change_id}")
def get_change(change_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    row = impact.visible_change(conn, user, change_id)
    if row is None: raise ApiError(404, "not_found", "Change not found.")
    return dict(row)


@router.post("/{change_id}/analyse", status_code=202)
def analyse_change(change_id: str, conn: sqlite3.Connection = Depends(get_db), _user: sqlite3.Row = Depends(get_current_user)):
    if conn.execute("SELECT 1 FROM regulatory_changes WHERE id = ?", (change_id,)).fetchone() is None: raise ApiError(404, "not_found", "Change not found.")
    return {"change_id": change_id, "impacts_created": impact.analyse_change(conn, change_id)}


@router.get("/{change_id}/impacts")
def list_change_impacts(change_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    if impact.visible_change(conn, user, change_id) is None: raise ApiError(404, "not_found", "Change not found.")
    visible = access.visible_document_ids(conn, user)
    rows = conn.execute("SELECT i.*, d.name AS document_name, c.content AS chunk_content FROM impacts i JOIN documents d ON d.id=i.document_id JOIN document_chunks c ON c.id=i.document_chunk_id WHERE i.regulatory_change_id = ? AND i.document_id IN ({}) ORDER BY CASE i.impact_level WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END".format(",".join("?" * len(visible)) if visible else "NULL"), [change_id, *visible]).fetchall()
    return {"items": [dict(row) for row in rows]}
