"""The section 5.4 job model: rows in `jobs`, run via FastAPI BackgroundTasks.

    "Every upload/analysis endpoint returns 202 with a job_id; the client
    polls GET /jobs/{job_id}. Jobs run in FastAPI BackgroundTasks inside the
    API process, with state persisted in a jobs table so progress survives
    a page refresh and a crash is visible rather than silent. No Celery, no
    Redis, no broker."

Every write here commits immediately (`update_job` is the one place a job
row changes) so a concurrent `GET /jobs/{id}` sees the latest step even
while the background task is still running — that is the entire point of
persisting progress instead of holding it in memory.

A background task gets its own sqlite3 connection (via `conn_factory`,
normally `api.db.get_connection`) rather than reusing the request's
connection, which FastAPI closes as soon as the response is sent.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("ripple.jobs")

JobStatus = str  # "queued" | "running" | "succeeded" | "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(
    conn: sqlite3.Connection,
    job_type: str,
    subject_type: str,
    subject_id: str,
    *,
    initiated_by: str | None = None,
) -> str:
    """Insert a `queued` job row and return its id. Call this synchronously,
    in the request handler, before scheduling the background task — the
    202 response's `job_id` must already exist in the table by the time the
    client's first `GET /jobs/{id}` can possibly arrive."""
    job_id = uuid.uuid4().hex
    now = _now()
    conn.execute(
        """
        INSERT INTO jobs (
          id, job_type, subject_type, subject_id, status, progress, step,
          initiated_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'queued', 0, 'Queued', ?, ?, ?)
        """,
        (job_id, job_type, subject_type, subject_id, initiated_by, now, now),
    )
    conn.commit()
    return job_id


def add_usage(conn: sqlite3.Connection, job_id: str, usage: Any) -> None:
    """Increment persisted usage after one successful external call."""
    conn.execute(
        """UPDATE jobs
           SET prompt_tokens = prompt_tokens + ?,
               completion_tokens = completion_tokens + ?,
               estimated_cost_usd = CASE
                 WHEN ? IS NULL THEN estimated_cost_usd
                 ELSE COALESCE(estimated_cost_usd, 0) + ?
               END,
               updated_at = ?
           WHERE id = ?""",
        (
            int(usage.prompt_tokens),
            int(usage.completion_tokens),
            usage.estimated_cost_usd,
            usage.estimated_cost_usd,
            _now(),
            job_id,
        ),
    )
    conn.commit()


def append_error_context(
    conn: sqlite3.Connection,
    job_id: str,
    context: dict[str, Any],
) -> None:
    """Append non-secret external failure context to a job result."""
    row = conn.execute("SELECT result FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return
    result = json.loads(row["result"]) if row["result"] else {}
    errors = result.setdefault("error_context", [])
    errors.append(context)
    update_job(conn, job_id, result=result)


def update_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    status: JobStatus | None = None,
    progress: float | None = None,
    step: str | None = None,
    error_message: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    """Incremental, immediately-committed update. Only the fields passed
    are changed; the rest keep their current value. This is what makes
    progress survive a page refresh — every step of a job calls this
    instead of accumulating state to write once at the end."""
    fields: list[str] = []
    values: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if step is not None:
        fields.append("step = ?")
        values.append(step)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    if result is not None:
        fields.append("result = ?")
        values.append(json.dumps(result))
    if not fields:
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def list_jobs(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    return conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()


def job_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Section 9.8 shape: {id, job_type, status, progress, step,
    error_message, result}. `result` is stored as a JSON TEXT column and
    parsed back into an object here rather than handed to the client as a
    double-encoded string."""
    result_raw = row["result"]
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "progress": row["progress"],
        "step": row["step"],
        "error_message": row["error_message"],
        "result": json.loads(result_raw) if result_raw else None,
        "usage": {
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "estimated_cost_usd": row["estimated_cost_usd"],
        },
    }


def run_job(
    background_tasks: Any,
    conn_factory: Callable[[], sqlite3.Connection],
    job_id: str,
    target: Callable[[sqlite3.Connection, str], None],
) -> None:
    """Schedule `target(conn, job_id)` on a FastAPI `BackgroundTasks`
    instance, with its own connection and a last-resort safety net.

    `target` is expected to set the job to 'running' (with an initial
    `step`) as its first act, do its work with incremental `update_job`
    calls, and set a terminal status ('succeeded' or 'failed', with
    `error_message` set for the latter) itself — including for expected
    failures like a scanned PDF. The `except Exception` below exists only
    to guarantee a job never gets stuck at 'running' forever because of a
    bug: if `target` raises without having set a terminal status, this
    still marks the job failed rather than leaving it silently hung.
    """

    def _runner() -> None:
        conn = conn_factory()
        try:
            target(conn, job_id)
        except Exception:
            logger.exception("Job %s failed with an unhandled exception", job_id)
            try:
                update_job(
                    conn,
                    job_id,
                    status="failed",
                    error_message="An unexpected error occurred while processing this job.",
                )
            except Exception:
                logger.exception("Job %s: could not even record the failure", job_id)
        finally:
            conn.close()

    background_tasks.add_task(_runner)
