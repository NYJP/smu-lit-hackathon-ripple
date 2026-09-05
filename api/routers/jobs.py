"""Jobs (section 9.8 / section 5.4). Not built yet — the `jobs` table exists
(section 6) but the BackgroundTasks runner that writes to it arrives with
the ingestion wave (PRD build order step 3)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import jobs as job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

_WAVE = "the ingestion wave's job runner (build order step 3)"


@router.get("/{job_id}")
def get_job(
    job_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    row = job_service.get_job(conn, job_id)
    if row is None:
        raise ApiError(404, "not_found", "Job not found.")
    return job_service.job_to_dict(row)


@router.get("")
def list_jobs(
    status: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    return {"items": [job_service.job_to_dict(row) for row in job_service.list_jobs(conn, status)]}
