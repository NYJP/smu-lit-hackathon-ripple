"""Background corpus reconciliation and scan history."""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import get_connection, get_db
from api.errors import ApiError
from api.services import jobs, scanning

router = APIRouter(prefix="/scans", tags=["scans"])


class ScanCreate(BaseModel):
    scope: Literal["stale", "full", "document", "lineage"] = "stale"
    scope_id: str | None = None
    confirmed: bool = False


@router.get("/pending")
def scans_pending(
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    return scanning.gap_summary(conn)


@router.post("", status_code=202)
def create_scan(
    payload: ScanCreate,
    background_tasks: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    if payload.scope == "full" and not payload.confirmed:
        raise ApiError(422, "validation_error", "confirmed must be true for a full re-scan.")
    if payload.scope in {"document", "lineage"} and not payload.scope_id:
        raise ApiError(422, "validation_error", "scope_id is required for a narrowed scan.")
    scan_id, job_id, created = scanning.start_scan(
        conn,
        trigger="manual",
        scope=payload.scope,
        scope_id=payload.scope_id,
        initiated_by=user["id"],
    )
    if created:
        jobs.run_job(background_tasks, get_connection, job_id, scanning.run_scan_job)
    return {"scan_id": scan_id, "job_id": job_id, "status": "queued" if created else "active"}


@router.get("")
def list_scans(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    total = conn.execute("SELECT COUNT(*) AS n FROM scans").fetchone()["n"]
    rows = conn.execute(
        "SELECT * FROM scans ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{scan_id}")
def get_scan(
    scan_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Scan not found.")
    job = jobs.get_job(conn, row["job_id"]) if row["job_id"] else None
    new_impacts = conn.execute(
        """SELECT i.id AS impact_id, i.impact_level, d.name AS document_name,
                  chunk.section_path
           FROM impacts i JOIN documents d ON d.id=i.document_id
           JOIN document_chunks chunk ON chunk.id=i.document_chunk_id
           WHERE i.created_by_scan_id=?
           ORDER BY CASE i.impact_level WHEN 'high' THEN 0 WHEN 'medium' THEN 1
                    WHEN 'low' THEN 2 ELSE 3 END, d.name""",
        (scan_id,),
    ).fetchall()
    return {
        "scan": dict(row),
        "job": jobs.job_to_dict(job) if job else None,
        "new_impacts": [dict(item) for item in new_impacts],
    }
