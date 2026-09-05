"""Dashboard summaries for visible documents and regulatory changes."""

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
    recent_changes = conn.execute(
        """SELECT c.*,
                  COUNT(DISTINCT CASE WHEN i.impact_level <> 'none' THEN i.id END) AS impact_count
           FROM regulatory_changes c
           LEFT JOIN impacts i ON i.regulatory_change_id = c.id
           GROUP BY c.id
           ORDER BY c.created_at DESC
           LIMIT 10"""
    ).fetchall()
    return {
        "impact_counts": {row["impact_level"]: row["n"] for row in counts},
        "documents_visible": len(visible),
        "recent_changes": [dict(row) for row in recent_changes],
    }
