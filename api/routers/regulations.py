"""Regulation ingestion and readback (PRD sections 5.4, 7.1, and 9.1)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile

from api.access import require_admin
from api.auth import get_current_user
from api.db import get_connection, get_db
from api.errors import ApiError
from api.services import jobs, openai, parsing, retrieval, storage

router = APIRouter(prefix="/regulations", tags=["regulations"])

_KINDS = {"primary", "amendment", "guidance", "notice", "decision", "consultation"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ingest_regulation(conn: sqlite3.Connection, job_id: str) -> None:
    job = jobs.get_job(conn, job_id)
    if job is None:
        return
    regulation_id = job["subject_id"]
    row = conn.execute("SELECT file_path, amends_regulation_id FROM regulations WHERE id = ?", (regulation_id,)).fetchone()
    if row is None:
        jobs.update_job(conn, job_id, status="failed", error_message="Regulation not found.")
        return
    jobs.update_job(conn, job_id, status="running", progress=0.1, step="Reading PDF")
    conn.execute("UPDATE regulations SET status = 'processing', error_message = NULL WHERE id = ?", (regulation_id,))
    conn.commit()
    try:
        parsed = parsing.parse_regulation_pdf(storage.absolute_path(row["file_path"]))
        storage.enforce_pdf_page_count(parsed.page_count)
    except parsing.ScannedPdfError:
        conn.execute(
            "UPDATE regulations SET status = 'failed', error_message = ? WHERE id = ?",
            (parsing.SCANNED_PDF_MESSAGE, regulation_id),
        )
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="Failed", error_message=parsing.SCANNED_PDF_MESSAGE)
        return
    except ApiError as exc:
        conn.execute("UPDATE regulations SET status = 'failed', error_message = ? WHERE id = ?", (exc.message, regulation_id))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="Failed", error_message=exc.message)
        return
    except Exception:
        message = "The regulation could not be processed."
        conn.execute("UPDATE regulations SET status = 'failed', error_message = ? WHERE id = ?", (message, regulation_id))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="Failed", error_message=message)
        return

    jobs.update_job(conn, job_id, progress=0.35, step="Extracting requirements")
    try:
        extracted, usage = retrieval.extract_requirements(conn, parsed)
        jobs.update_job(conn, job_id, progress=0.75, step="Saving requirements")
        requirement_count = retrieval.persist_requirements(conn, regulation_id, row["amends_regulation_id"], extracted)
    except openai.ExternalServiceError as exc:
        message = str(exc)
        conn.execute("UPDATE regulations SET status = 'failed', error_message = ? WHERE id = ?", (message, regulation_id))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="Failed", error_message=message)
        return
    conn.execute("UPDATE regulations SET page_count = ?, status = 'ready', error_message = NULL WHERE id = ?", (parsed.page_count, regulation_id))
    conn.commit()
    jobs.update_job(
        conn, job_id, status="succeeded", progress=1, step="Ready",
        result={"page_count": parsed.page_count, "requirement_count": requirement_count, "token_usage": usage.as_dict(), "estimated_cost_usd": _estimated_cost(usage)},
    )


def _estimated_cost(usage: openai.Usage) -> float:
    """Conservative displayed estimate; usage remains the authoritative record."""
    return round((usage.prompt_tokens * 5 + usage.completion_tokens * 15) / 1_000_000, 8)


@router.post("", status_code=202)
async def upload_regulation(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    document_kind: str = Form("primary"),
    amends_regulation_id: str | None = Form(None),
    effective_date: str | None = Form(None),
    jurisdiction: str | None = Form(None),
    _admin: sqlite3.Row = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    openai.require_configured()
    if document_kind not in _KINDS:
        raise ApiError(422, "validation_error", "Invalid document kind.")
    if not title.strip():
        raise ApiError(422, "validation_error", "Title is required.")
    if storage.extension_of(file.filename or "") != ".pdf":
        raise ApiError(400, "bad_request", "Regulations must be uploaded as PDF files.")
    if amends_regulation_id and conn.execute("SELECT 1 FROM regulations WHERE id = ?", (amends_regulation_id,)).fetchone() is None:
        raise ApiError(404, "not_found", "Regulation to amend not found.")
    content = await file.read()
    storage.enforce_file_size(len(content), file.filename or "upload.pdf")
    relative_path, _mime_type = storage.save_upload("regulations", file.filename or "upload.pdf", content)
    regulation_id = uuid.uuid4().hex
    try:
        conn.execute(
            """INSERT INTO regulations
               (id, title, jurisdiction, document_kind, amends_regulation_id, effective_date,
                file_path, file_name, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (regulation_id, title.strip(), jurisdiction, document_kind, amends_regulation_id,
             effective_date, relative_path, file.filename or "upload.pdf", _now()),
        )
        job_id = jobs.create_job(conn, "regulation_ingest", "regulation", regulation_id)
    except Exception:
        storage.delete_file(relative_path)
        raise
    jobs.run_job(background_tasks, get_connection, job_id, _ingest_regulation)
    return {"regulation_id": regulation_id, "job_id": job_id}


@router.get("")
def list_regulations(
    limit: int = 50,
    cursor: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    if not 1 <= limit <= 200:
        raise ApiError(422, "validation_error", "limit must be between 1 and 200.")
    rows = conn.execute(
        """SELECT r.*, (SELECT COUNT(*) FROM regulatory_requirements q WHERE q.regulation_id = r.id) AS requirement_count,
                   (SELECT COUNT(*) FROM regulatory_changes c WHERE c.detected_from_regulation_id = r.id) AS change_count
           FROM regulations r WHERE (? IS NULL OR r.created_at < ?)
           ORDER BY r.created_at DESC, r.id DESC LIMIT ?""",
        (cursor, cursor, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [{key: row[key] for key in ("id", "title", "document_kind", "status", "requirement_count", "change_count", "created_at")} for row in rows], "next_cursor": rows[-1]["created_at"] if more else None}


@router.get("/{regulation_id}")
def get_regulation(regulation_id: str, conn: sqlite3.Connection = Depends(get_db), _user: sqlite3.Row = Depends(get_current_user)):
    regulation = conn.execute("SELECT * FROM regulations WHERE id = ?", (regulation_id,)).fetchone()
    if regulation is None:
        raise ApiError(404, "not_found", "Regulation not found.")
    requirements = conn.execute("SELECT * FROM regulatory_requirements WHERE regulation_id = ? ORDER BY source_page, id", (regulation_id,)).fetchall()
    changes = conn.execute("SELECT * FROM regulatory_changes WHERE detected_from_regulation_id = ? ORDER BY created_at DESC", (regulation_id,)).fetchall()
    return {"regulation": dict(regulation), "requirements": [dict(row) for row in requirements], "changes": [dict(row) for row in changes]}


@router.delete("/{regulation_id}", status_code=204)
def delete_regulation(regulation_id: str, conn: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(require_admin)):
    row = conn.execute("SELECT file_path FROM regulations WHERE id = ?", (regulation_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Regulation not found.")
    conn.execute("DELETE FROM regulations WHERE id = ?", (regulation_id,))
    conn.commit()
    storage.delete_file(row["file_path"])
    return None
