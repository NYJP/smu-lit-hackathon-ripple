"""Organization-wide regulatory change and affected-content APIs."""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from api.auth import get_current_user
from api.db import get_connection, get_db
from api.errors import ApiError
from api.services import changes as change_service
from api.services import impact, jobs, scanning

router = APIRouter(prefix="/changes", tags=["changes"])
_LEVEL_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}


def _require_change(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    change_id: str,
) -> sqlite3.Row:
    row = impact.visible_change(conn, user, change_id)
    if row is None:
        raise ApiError(404, "not_found", "Change not found.")
    return row


def _counts(conn: sqlite3.Connection, change_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT impact_level, COUNT(*) AS n FROM impacts WHERE regulatory_change_id = ? GROUP BY impact_level",
        (change_id,),
    ).fetchall()
    result = {"high": 0, "medium": 0, "low": 0, "none": 0}
    result.update({row["impact_level"]: row["n"] for row in rows})
    return result


@router.get("")
def list_changes(
    include_simulated: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    where = "1 = 1" if include_simulated else "c.simulation_id IS NULL"
    total = conn.execute(f"SELECT COUNT(*) AS n FROM regulatory_changes c WHERE {where}").fetchone()["n"]
    rows = conn.execute(
        f"""SELECT c.*,
                   COALESCE(source_reg.title, origin_reg.title) AS regulation_title,
                   COUNT(DISTINCT CASE WHEN i.impact_level <> 'none' THEN i.document_id END)
                     AS affected_document_count,
                   SUM(CASE WHEN i.impact_level='high' THEN 1 ELSE 0 END) AS high_count,
                   SUM(CASE WHEN i.impact_level='medium' THEN 1 ELSE 0 END) AS medium_count,
                   SUM(CASE WHEN i.impact_level='low' THEN 1 ELSE 0 END) AS low_count,
                   SUM(CASE WHEN i.impact_level='none' THEN 1 ELSE 0 END) AS none_count
            FROM regulatory_changes c
            LEFT JOIN requirement_lineages l ON l.id = c.lineage_id
            LEFT JOIN regulations origin_reg ON origin_reg.id = l.origin_regulation_id
            LEFT JOIN regulations source_reg ON source_reg.id = c.detected_from_regulation_id
            LEFT JOIN impacts i ON i.regulatory_change_id = c.id
            WHERE {where}
            GROUP BY c.id
            ORDER BY c.created_at DESC, c.id DESC
            LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["counts"] = {
            "high": item.pop("high_count") or 0,
            "medium": item.pop("medium_count") or 0,
            "low": item.pop("low_count") or 0,
            "none": item.pop("none_count") or 0,
        }
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{change_id}")
def get_change(
    change_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    change = _require_change(conn, user, change_id)
    previous, proposed = change_service.get_change_requirement_pair(conn, change)
    regulation = conn.execute(
        """SELECT r.* FROM regulations r
           WHERE r.id = COALESCE(
             ?,
             (SELECT origin_regulation_id FROM requirement_lineages WHERE id = ?)
           )""",
        (change["detected_from_regulation_id"], change["lineage_id"]),
    ).fetchone()
    documents = conn.execute(
        """SELECT d.id AS document_id, d.name, d.doc_type,
                  u.id AS owner_id, u.display_name AS owner_name,
                  COUNT(i.id) AS impact_count,
                  MIN(CASE i.impact_level WHEN 'high' THEN 0 WHEN 'medium' THEN 1
                      WHEN 'low' THEN 2 ELSE 3 END) AS level_rank
           FROM impacts i
           JOIN documents d ON d.id = i.document_id
           JOIN users u ON u.id = d.owner_id
           WHERE i.regulatory_change_id = ? AND i.impact_level <> 'none'
           GROUP BY d.id, u.id
           ORDER BY level_rank, d.name COLLATE NOCASE""",
        (change_id,),
    ).fetchall()
    rank_level = {value: key for key, value in _LEVEL_RANK.items()}
    affected_documents = []
    for row in documents:
        item = dict(row)
        item["owner"] = {"id": item.pop("owner_id"), "display_name": item.pop("owner_name")}
        item["max_impact_level"] = rank_level[item.pop("level_rank")]
        affected_documents.append(item)
    return {
        "change": dict(change),
        "regulation": dict(regulation) if regulation else None,
        "previous_requirement": previous,
        "new_requirement": proposed,
        "counts": _counts(conn, change_id),
        "affected_documents": affected_documents,
    }


@router.post("/{change_id}/analyse", status_code=202)
def analyse_change(
    change_id: str,
    background_tasks: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    _require_change(conn, user, change_id)
    active = conn.execute(
        """SELECT id FROM jobs WHERE job_type='change_analysis' AND subject_id=?
           AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1""",
        (change_id,),
    ).fetchone()
    if active:
        return {"change_id": change_id, "job_id": active["id"]}
    job_id = jobs.create_job(
        conn, "change_analysis", "regulatory_change", change_id,
        initiated_by=user["id"], input_payload={"change_id": change_id},
    )
    jobs.run_job(background_tasks, get_connection, job_id, scanning.run_change_analysis_job)
    return {"change_id": change_id, "job_id": job_id}


@router.get("/{change_id}/impacts")
def list_change_impacts(
    change_id: str,
    impact_level: Literal["high", "medium", "low", "none"] | None = None,
    document_id: str | None = None,
    owner_id: str | None = None,
    review_status: Literal["open", "in_review", "resolved", "dismissed"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    _require_change(conn, user, change_id)
    filters = ["i.regulatory_change_id = ?"]
    values: list[object] = [change_id]
    for clause, value in (
        ("i.impact_level = ?", impact_level),
        ("i.document_id = ?", document_id),
        ("d.owner_id = ?", owner_id),
        ("i.review_status = ?", review_status),
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
        f"""SELECT i.id AS impact_id, i.impact_level, i.confidence, i.reason,
                   i.review_status, i.conflicting_span, i.conflicting_start,
                   i.conflicting_end, i.created_at,
                   d.id AS document_id, d.name AS document_name, d.doc_type,
                   u.id AS owner_id, u.display_name AS owner_name,
                   chunk.id AS chunk_id, chunk.content AS chunk_content,
                   chunk.section_path, chunk.page_number,
                   dep.id AS dependency_id, dep.relationship_type,
                   dep.confidence AS dependency_confidence,
                   rec.id AS recommendation_id, rec.status AS recommendation_status,
                   rec.suggested_text, rec.generation_method, rec.source_citations
            FROM impacts i
            JOIN documents d ON d.id = i.document_id
            JOIN users u ON u.id = d.owner_id
            JOIN document_chunks chunk ON chunk.id = i.document_chunk_id
            JOIN dependencies dep ON dep.id = i.dependency_id
            LEFT JOIN recommendations rec ON rec.impact_id = i.id
            WHERE {where}
            ORDER BY CASE i.impact_level WHEN 'high' THEN 0 WHEN 'medium' THEN 1
                     WHEN 'low' THEN 2 ELSE 3 END, d.name COLLATE NOCASE, i.id
            LIMIT ? OFFSET ?""",
        [*values, limit, offset],
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        citations = item.get("source_citations")
        if citations:
            item["source_citations"] = json.loads(citations)
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
