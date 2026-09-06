"""Organization-wide background job status and retry controls."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends

from api.auth import get_current_user
from api.db import get_connection, get_db
from api.errors import ApiError
from api.services import jobs as job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

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


@router.post("/{job_id}/retry", status_code=202)
def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    source = job_service.get_job(conn, job_id)
    if source is None:
        raise ApiError(404, "not_found", "Job not found.")
    supported = {"document_ingest", "regulation_ingest", "change_analysis", "simulation_run", "scan"}
    if source["job_type"] not in supported:
        raise ApiError(409, "conflict", "This job type cannot be retried yet.")
    try:
        new_job_id = job_service.retry_job(conn, job_id, user["id"])
    except ValueError as exc:
        raise ApiError(409, "conflict", str(exc)) from exc

    if source["job_type"] == "document_ingest":
        from api.routers.documents import _ingest_document
        conn.execute("UPDATE documents SET status='pending', error_message=NULL WHERE id=?", (source["subject_id"],))
        target = _ingest_document
    elif source["job_type"] == "regulation_ingest":
        from api.routers.regulations import _ingest_regulation
        conn.execute("UPDATE regulations SET status='pending', error_message=NULL WHERE id=?", (source["subject_id"],))
        target = _ingest_regulation
    elif source["job_type"] == "change_analysis":
        from api.services.scanning import run_change_analysis_job
        target = run_change_analysis_job
    elif source["job_type"] == "simulation_run":
        from api.services.simulations import run_simulation_job
        target = run_simulation_job
    else:
        from api.services.scanning import run_scan_job
        conn.execute(
            """UPDATE scans SET status='queued', job_id=?, error_message=NULL,
                 started_at=NULL, finished_at=NULL, documents_scanned=0,
                 requirements_scanned=0, mapping_pairs_checked=0,
                 dependencies_added=0, dependencies_removed=0, impacts_created=0,
                 new_high_impacts=0, cache_hits=0, prompt_tokens=0,
                 completion_tokens=0, estimated_cost_usd=0 WHERE id=?""",
            (new_job_id, source["subject_id"]),
        )
        target = run_scan_job
    conn.commit()
    job_service.run_job(background_tasks, get_connection, new_job_id, target)
    return {"job_id": new_job_id, "retry_of_job_id": job_id}
