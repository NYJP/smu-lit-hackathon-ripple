"""Organization-wide impact review and recommendation generation APIs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import changes as change_service
from api.services import recommendations as recommendation_service

router = APIRouter(prefix="/impacts", tags=["impacts"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImpactPatch(BaseModel):
    review_status: Literal["open", "in_review", "resolved", "dismissed"]


def _require_impact(conn: sqlite3.Connection, impact_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM impacts WHERE id = ?", (impact_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Impact not found.")
    return row


def _recommendation(conn: sqlite3.Connection, impact_id: str) -> dict | None:
    row = conn.execute(
        """SELECT r.*, u.display_name AS decided_by_name
           FROM recommendations r
           LEFT JOIN users u ON u.id = r.decided_by
           WHERE r.impact_id = ?""",
        (impact_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["source_citations"] = json.loads(result["source_citations"] or "[]")
    result["decision_history"] = [
        dict(item) for item in conn.execute(
            """SELECT rd.*, u.display_name AS decided_by_name
               FROM recommendation_decisions rd
               JOIN users u ON u.id = rd.decided_by
               WHERE rd.recommendation_id = ?
               ORDER BY rd.decided_at, rd.id""",
            (row["id"],),
        ).fetchall()
    ]
    return result


@router.get("")
def list_impacts(
    impact_level: Literal["high", "medium", "low", "none"] | None = None,
    review_status: Literal["open", "in_review", "resolved", "dismissed"] | None = None,
    document_id: str | None = None,
    owner_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    filters = ["1 = 1"]
    values: list[object] = []
    for clause, value in (
        ("i.impact_level = ?", impact_level),
        ("i.review_status = ?", review_status),
        ("i.document_id = ?", document_id),
        ("d.owner_id = ?", owner_id),
    ):
        if value is not None:
            filters.append(clause)
            values.append(value)
    where = " AND ".join(filters)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM impacts i JOIN documents d ON d.id=i.document_id WHERE {where}",
        values,
    ).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT i.*, d.name AS document_name, d.doc_type,
                   u.id AS owner_id, u.display_name AS owner_name,
                   c.summary AS change_summary, c.source, c.simulation_id,
                   chunk.section_path, chunk.page_number
            FROM impacts i
            JOIN documents d ON d.id=i.document_id
            JOIN users u ON u.id=d.owner_id
            JOIN regulatory_changes c ON c.id=i.regulatory_change_id
            JOIN document_chunks chunk ON chunk.id=i.document_chunk_id
            WHERE {where}
            ORDER BY CASE i.impact_level WHEN 'high' THEN 0 WHEN 'medium' THEN 1
                     WHEN 'low' THEN 2 ELSE 3 END, i.created_at DESC, i.id
            LIMIT ? OFFSET ?""",
        [*values, limit, offset],
    ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{impact_id}")
def get_impact(
    impact_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    impact = _require_impact(conn, impact_id)
    change = conn.execute(
        "SELECT * FROM regulatory_changes WHERE id = ?", (impact["regulatory_change_id"],)
    ).fetchone()
    previous, proposed = change_service.get_change_requirement_pair(conn, change)
    dependency = conn.execute(
        "SELECT * FROM dependencies WHERE id = ?", (impact["dependency_id"],)
    ).fetchone()
    chunk = conn.execute(
        "SELECT * FROM document_chunks WHERE id = ?", (impact["document_chunk_id"],)
    ).fetchone()
    document = conn.execute(
        """SELECT d.*, u.display_name AS owner_name
           FROM documents d JOIN users u ON u.id=d.owner_id WHERE d.id=?""",
        (impact["document_id"],),
    ).fetchone()
    collaborators = conn.execute(
        """SELECT u.id, u.display_name, dc.access
           FROM document_collaborators dc JOIN users u ON u.id=dc.user_id
           WHERE dc.document_id=? ORDER BY u.display_name COLLATE NOCASE""",
        (impact["document_id"],),
    ).fetchall()
    requirement = proposed or previous or {}
    regulation_id = requirement.get("regulation_id")
    if regulation_id is None:
        origin = conn.execute(
            "SELECT origin_regulation_id FROM requirement_lineages WHERE id=?", (change["lineage_id"],)
        ).fetchone()
        regulation_id = origin["origin_regulation_id"] if origin else None
    regulation = conn.execute("SELECT * FROM regulations WHERE id=?", (regulation_id,)).fetchone() if regulation_id else None
    review_history = [
        dict(row) for row in conn.execute(
            """SELECT e.*, u.display_name AS changed_by_name
               FROM impact_review_events e JOIN users u ON u.id=e.changed_by
               WHERE e.impact_id=? ORDER BY e.changed_at, e.id""",
            (impact_id,),
        ).fetchall()
    ]
    recommendation = _recommendation(conn, impact_id)
    return {
        "impact": dict(impact),
        "change": dict(change),
        "regulation": dict(regulation) if regulation else None,
        "previous_requirement": previous,
        "new_requirement": proposed,
        "dependency": dict(dependency),
        "document": {
            **dict(document),
            "owner": {"id": document["owner_id"], "display_name": document["owner_name"]},
            "collaborators": [dict(row) for row in collaborators],
        },
        "chunk": dict(chunk),
        "recommendation": recommendation,
        "review_history": review_history,
        "capabilities": {
            "change_review_status": True,
            "generate_recommendation": True,
            "decide_recommendation": True,
            "accept_recommendation": change["source"] != "simulation",
        },
    }


@router.patch("/{impact_id}")
def patch_impact(
    impact_id: str,
    payload: ImpactPatch,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    current = _require_impact(conn, impact_id)
    if current["review_status"] == payload.review_status:
        return get_impact(impact_id, conn, user)
    now = _now()
    conn.execute(
        """INSERT INTO impact_review_events
           (id, impact_id, previous_status, new_status, changed_by, changed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (uuid.uuid4().hex, impact_id, current["review_status"], payload.review_status, user["id"], now),
    )
    terminal = payload.review_status in {"resolved", "dismissed"}
    conn.execute(
        """UPDATE impacts SET review_status=?, resolved_by=?, resolved_at=? WHERE id=?""",
        (payload.review_status, user["id"] if terminal else None, now if terminal else None, impact_id),
    )
    conn.commit()
    return get_impact(impact_id, conn, user)


@router.post("/{impact_id}/recommendation", status_code=201)
def generate_recommendation(
    impact_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    _require_impact(conn, impact_id)
    recommendation, usage = recommendation_service.generate(conn, impact_id)
    conn.commit()
    return {"recommendation": recommendation, "usage": usage.as_dict()}
