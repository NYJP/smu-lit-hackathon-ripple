"""Dashboard (section 9.8). Not built yet — arrives with the impact engine
wave (PRD build order step 7), the earliest point at which totals, recent
changes, and an attention panel are all meaningful."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.db import get_db
from api import access

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    visible = access.visible_document_ids(conn, user)
    ph = ",".join("?" * len(visible)) if visible else "NULL"
    counts = conn.execute(f"SELECT impact_level, COUNT(*) AS n FROM impacts WHERE document_id IN ({ph}) GROUP BY impact_level", list(visible)).fetchall()
    return {"impact_counts": {row["impact_level"]: row["n"] for row in counts}, "documents_visible": len(visible), "recent_changes": [dict(row) for row in conn.execute("SELECT * FROM regulatory_changes ORDER BY created_at DESC LIMIT 10").fetchall()]}
