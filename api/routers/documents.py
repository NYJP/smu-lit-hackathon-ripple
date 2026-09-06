"""Document ingestion, visibility-scoped reading, and collaborator tagging."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from api import access
from api.auth import get_current_user
from api.db import get_connection, get_db
from api.errors import ApiError
from api.services import clauses, contributions, jobs, mapping, openai, parsing, patching, retrieval, scanning, storage
from api.services import severity as severity_service
from api.services import workflow

router = APIRouter(prefix="/documents", tags=["documents"])

_DOC_TYPES = {"policy", "playbook", "sop", "template", "clause_library", "checklist", "opinion", "advisory", "training", "other"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollaboratorsIn(BaseModel):
    user_ids: list[str] = Field(min_length=1)
    access: Literal["viewer", "reviewer"] = "reviewer"


class DocumentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    doc_type: str | None = None
    version_label: str | None = Field(default=None, max_length=200)
    owner_id: str | None = None


def _max_open_severity(conn: sqlite3.Connection, document_ids: list[str]) -> dict[str, str]:
    """Highest still-open severity per document, keyed by document id.

    One query for the whole page. Severity is derived per impact (the parent
    change's effective date decides the critical escalation), so this cannot
    be a plain SQL MAX over `impact_level`.
    """
    if not document_ids:
        return {}
    placeholders = ",".join("?" * len(document_ids))
    open_clause, open_values = workflow.open_status_sql("i.review_status")
    rows = conn.execute(
        f"""SELECT i.document_id, i.impact_level, i.confidence,
                   c.change_type, c.effective_date
              FROM impacts i
              JOIN regulatory_changes c ON c.id = i.regulatory_change_id
             WHERE i.document_id IN ({placeholders})
               AND i.impact_level <> 'none'
               AND {open_clause}""",
        [*document_ids, *open_values],
    ).fetchall()
    worst: dict[str, str] = {}
    for row in rows:
        level = severity_service.derive_severity(row, row)
        current = worst.get(row["document_id"], "none")
        if severity_service.SEVERITY_RANK[level] > severity_service.SEVERITY_RANK[current]:
            worst[row["document_id"]] = level
    return worst


def _document_collaborators(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT u.id, u.display_name, dc.access FROM document_collaborators dc
           JOIN users u ON u.id = dc.user_id WHERE dc.document_id = ?
           ORDER BY u.display_name COLLATE NOCASE""", (document_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def _ingest_document(conn: sqlite3.Connection, job_id: str) -> None:
    job = jobs.get_job(conn, job_id)
    if job is None:
        return
    document_id = job["subject_id"]
    document = conn.execute("SELECT file_path, mime_type FROM documents WHERE id = ?", (document_id,)).fetchone()
    if document is None:
        jobs.update_job(conn, job_id, status="failed", error_message="Document not found.")
        return
    jobs.update_job(conn, job_id, status="running", progress=0.1, step="Reading document")
    conn.execute("UPDATE documents SET status = 'processing', error_message = NULL WHERE id = ?", (document_id,))
    conn.commit()
    try:
        parsed = parsing.parse_and_chunk_document(storage.absolute_path(document["file_path"]), document["mime_type"])
        if parsed.page_count is not None:
            storage.enforce_pdf_page_count(parsed.page_count)
    except parsing.ScannedPdfError:
        conn.execute("UPDATE documents SET status = 'failed', error_message = ? WHERE id = ?", (parsing.SCANNED_PDF_MESSAGE, document_id))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="Failed", error_message=parsing.SCANNED_PDF_MESSAGE)
        return
    except ApiError as exc:
        conn.execute("UPDATE documents SET status = 'failed', error_message = ? WHERE id = ?", (exc.message, document_id))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="Failed", error_message=exc.message)
        return
    except Exception:
        message = "The document could not be processed."
        conn.execute("UPDATE documents SET status = 'failed', error_message = ? WHERE id = ?", (message, document_id))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="Failed", error_message=message)
        return

    jobs.update_job(conn, job_id, progress=0.65, step="Saving chunks")
    now = _now()
    embeddings: dict[int, list[float]] = {}
    embedding_usage = openai.Usage()
    unembedded_count = 0
    try:
        jobs.update_job(conn, job_id, progress=0.5, step="Embedding chunks")
        embeddings, embedding_usage = retrieval.embed_chunks(parsed.chunks)
        jobs.add_usage(conn, job_id, embedding_usage)
    except openai.ExternalServiceError:
        # A failed embedding batch leaves the parsed document readable and
        # keyword-searchable; the job records the gap for reindex recovery.
        unembedded_count = sum(1 for chunk in parsed.chunks if chunk.chunk_type != "heading" and len(chunk.content) >= 60)
    try:
        with conn:
            # Reuse chunk ids by ordinal so dependencies survive a re-upload
            # long enough for G3 to inspect their evidence against new text.
            old_chunks = {
                row["ordinal"]: row for row in conn.execute(
                    "SELECT * FROM document_chunks WHERE document_id=?", (document_id,)
                ).fetchall()
            }
            conn.execute("DELETE FROM fts_chunks WHERE chunk_id IN (SELECT id FROM document_chunks WHERE document_id = ?)", (document_id,))
            for old_chunk in old_chunks.values():
                conn.execute("DELETE FROM vec_chunks WHERE chunk_id=?", (old_chunk["id"],))
            current_ordinals: set[int] = set()
            for chunk in parsed.chunks:
                current_ordinals.add(chunk.ordinal)
                existing_chunk = old_chunks.get(chunk.ordinal)
                chunk_id = existing_chunk["id"] if existing_chunk else uuid.uuid4().hex
                if existing_chunk:
                    conn.execute(
                        """UPDATE document_chunks SET content=?, section_path=?, section_title=?,
                           page_number=?, char_start=?, char_end=?, chunk_type=? WHERE id=?""",
                        (chunk.content, chunk.section_path, chunk.section_title, chunk.page_number,
                         chunk.char_start, chunk.char_end, chunk.chunk_type, chunk_id),
                    )
                else:
                    conn.execute(
                        """INSERT INTO document_chunks
                           (id, document_id, ordinal, content, section_path, section_title, page_number,
                            char_start, char_end, chunk_type, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (chunk_id, document_id, chunk.ordinal, chunk.content, chunk.section_path,
                         chunk.section_title, chunk.page_number, chunk.char_start, chunk.char_end,
                         chunk.chunk_type, now),
                    )
                conn.execute("INSERT INTO fts_chunks (chunk_id, content, section_path) VALUES (?, ?, ?)", (chunk_id, chunk.content, chunk.section_path or ""))
                if chunk.ordinal in embeddings:
                    import sqlite_vec
                    conn.execute("INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)", (chunk_id, sqlite_vec.serialize_float32(embeddings[chunk.ordinal])))
            for ordinal, old_chunk in old_chunks.items():
                if ordinal in current_ordinals:
                    continue
                linked = conn.execute(
                    "SELECT 1 FROM dependencies WHERE document_chunk_id=? LIMIT 1", (old_chunk["id"],)
                ).fetchone()
                if linked:
                    conn.execute(
                        """UPDATE document_chunks SET content='', section_title='Removed content',
                           chunk_type='other', char_start=NULL, char_end=NULL WHERE id=?""",
                        (old_chunk["id"],),
                    )
                else:
                    conn.execute("DELETE FROM document_chunks WHERE id=?", (old_chunk["id"],))
            conn.execute("UPDATE documents SET page_count = ?, status = 'ready', error_message = NULL WHERE id = ?", (parsed.page_count, document_id))
            owner = conn.execute("SELECT owner_id FROM documents WHERE id = ?", (document_id,)).fetchone()
            contributions.assign_document_to_owner(conn, document_id, owner["owner_id"])
    except Exception:
        message = "The document could not be saved."
        conn.execute("UPDATE documents SET status = 'failed', error_message = ? WHERE id = ?", (message, document_id))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="Failed", error_message=message)
        return
    mapping_result = mapping.MappingResult()
    mapping_error = None
    try:
        jobs.update_job(conn, job_id, progress=0.85, step="Mapping dependencies")
        mapping_result = mapping.map_document(conn, document_id, job_id=job_id)
    except openai.ExternalServiceError as exc:
        # Parsed content remains available even if dependency analysis cannot
        # complete; the mapping gap can be safely retried by the scan wave.
        mapping_error = str(exc)
    usage = embedding_usage.add(mapping_result.usage)
    scan_id, scan_job_id, scan_created = scanning.start_scan(
        conn, trigger="document_added", scope="document", scope_id=document_id
    )
    jobs.update_job(conn, job_id, status="succeeded", progress=1, step="completed", result={"chunk_count": len(parsed.chunks), "page_count": parsed.page_count, "unembedded_count": unembedded_count, "dependencies_added": mapping_result.dependencies_added, "mapping_candidates_seen": mapping_result.candidates_seen, "mapping_error": mapping_error, "token_usage": usage.as_dict(), "estimated_cost_usd": usage.estimated_cost_usd, "scan_id": scan_id, "scan_job_id": scan_job_id})
    if scan_created:
        scanning.run_scan_job(conn, scan_job_id)


@router.post("", status_code=202)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., alias="files[]"),
    doc_type: str = Form("policy"),
    version_label: str | None = Form(None),
    collaborator_ids: list[str] | None = Form(None, alias="collaborator_ids[]"),
    collaborator_access: Literal["viewer", "reviewer"] = Form("reviewer"),
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    openai.require_configured()
    if doc_type not in _DOC_TYPES:
        raise ApiError(422, "validation_error", "Invalid document type.")
    storage.enforce_batch_size(len(files))
    collaborator_ids = list(dict.fromkeys(collaborator_ids or []))
    if collaborator_ids:
        found = conn.execute("SELECT id FROM users WHERE id IN (%s)" % ",".join("?" * len(collaborator_ids)), collaborator_ids).fetchall()
        if len(found) != len(collaborator_ids):
            raise ApiError(404, "not_found", "Collaborator not found.")
    prepared: list[tuple[UploadFile, bytes, str]] = []
    for file in files:
        content = await file.read()
        filename = file.filename or "upload"
        storage.enforce_file_size(len(content), filename)
        mime_type = storage.mime_type_for(filename)
        prepared.append((file, content, mime_type))
    responses: list[dict[str, str | None]] = []
    for file, content, mime_type in prepared:
        filename = file.filename or "upload"
        relative_path, _ = storage.save_upload("documents", filename, content)
        document_id = uuid.uuid4().hex
        try:
            conn.execute(
                """INSERT INTO documents (id, owner_id, name, doc_type, version_label, file_path,
                   file_name, mime_type, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (document_id, user["id"], filename, doc_type, version_label, relative_path, filename, mime_type, _now()),
            )
            for collaborator_id in collaborator_ids:
                if collaborator_id != user["id"]:
                    conn.execute(
                        """INSERT INTO document_collaborators (document_id, user_id, access, added_by, added_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (document_id, collaborator_id, collaborator_access, user["id"], _now()),
                    )
            job_id = jobs.create_job(
                conn, "document_ingest", "document", document_id,
                initiated_by=user["id"], input_payload={"document_id": document_id},
            )
        except Exception:
            conn.rollback()
            storage.delete_file(relative_path)
            raise
        jobs.run_job(background_tasks, get_connection, job_id, _ingest_document)
        responses.append({"document_id": document_id, "job_id": job_id, "scan_id": None})
    return {"documents": responses}


@router.get("")
def list_documents(
    scope: Literal["mine", "shared_with_me", "all"] = "all",
    limit: int = 50,
    cursor: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    if not 1 <= limit <= 200:
        raise ApiError(422, "validation_error", "limit must be between 1 and 200.")
    visible = access.visible_document_ids(conn, user)
    if not visible:
        return {"items": [], "next_cursor": None}
    placeholders = ",".join("?" * len(visible))
    rows = conn.execute(
        f"""SELECT d.*, u.display_name AS owner_name,
                  (SELECT COUNT(*) FROM document_chunks c WHERE c.document_id = d.id) AS chunk_count,
                  (SELECT COUNT(*) FROM dependencies dep WHERE dep.document_id = d.id AND dep.status = 'active') AS dependency_count,
                  (SELECT COUNT(*) FROM impacts i
                    WHERE i.document_id = d.id
                      AND i.impact_level <> 'none'
                      AND i.review_status IN ('detected','awaiting_review','in_review',
                                              'needs_analysis','patch_proposed','awaiting_approval')) AS open_impact_count
             FROM documents d JOIN users u ON u.id = d.owner_id
             WHERE d.id IN ({placeholders}) AND (? IS NULL OR d.created_at < ?)
             ORDER BY d.created_at DESC, d.id DESC""",
        [*visible, cursor, cursor],
    ).fetchall()
    if scope == "mine":
        rows = [row for row in rows if row["owner_id"] == user["id"]]
    elif scope == "shared_with_me":
        rows = [row for row in rows if row["owner_id"] != user["id"] and any(c["id"] == user["id"] for c in _document_collaborators(conn, row["id"]))]
    more = len(rows) > limit
    rows = rows[:limit]
    # Worst open severity per document, in one query rather than per row.
    # Derived rather than a SQL MAX(impact_level) because the critical
    # escalation depends on the parent change's effective date.
    severity_by_document = _max_open_severity(conn, [row["id"] for row in rows])
    items = []
    for row in rows:
        item = {key: row[key] for key in ("id", "name", "doc_type", "status", "page_count", "chunk_count", "dependency_count", "open_impact_count", "created_at")}
        item.update({
            "owner": {"id": row["owner_id"], "display_name": row["owner_name"]},
            "collaborators": _document_collaborators(conn, row["id"]),
            "contributors": contributions.for_document(conn, row["id"]),
            "max_severity": severity_by_document.get(row["id"], "none"),
            "last_scanned_at": None,
        })
        items.append(item)
    return {"items": items, "next_cursor": rows[-1]["created_at"] if more else None}


@router.get("/{document_id}/coverage")
def document_coverage(document_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    access.require_visible_document(conn, user, document_id)
    counts = conn.execute("SELECT COUNT(*) AS checked, COALESCE(SUM(dependency_found), 0) AS found, MAX(mapped_at) AS last_pass_at FROM mapping_passes WHERE document_id = ?", (document_id,)).fetchone()
    total = conn.execute("SELECT COUNT(*) AS total FROM requirement_lineages").fetchone()["total"]
    regulations = conn.execute(
        """SELECT r.id AS regulation_id, r.title, COUNT(l.id) AS requirements_total,
                  COALESCE(SUM(CASE WHEN p.document_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS requirements_checked,
                  COALESCE(SUM(CASE WHEN p.dependency_found = 1 THEN 1 ELSE 0 END), 0) AS dependencies_found
           FROM regulations r
           JOIN requirement_lineages l ON l.origin_regulation_id = r.id
           LEFT JOIN mapping_passes p ON p.lineage_id = l.id AND p.document_id = ?
           GROUP BY r.id, r.title ORDER BY r.title COLLATE NOCASE""",
        (document_id,),
    ).fetchall()
    return {
        "requirements_checked": counts["checked"], "dependencies_found": counts["found"],
        "last_pass_at": counts["last_pass_at"], "unchecked_lineage_count": max(0, total - counts["checked"]),
        "by_regulation": [dict(row) for row in regulations],
    }


@router.post("/{document_id}/collaborators")
def add_collaborators(document_id: str, payload: CollaboratorsIn, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    access.require_visible_document(conn, user, document_id)
    doc = conn.execute("SELECT owner_id FROM documents WHERE id = ?", (document_id,)).fetchone()
    if user["role"] != "admin" and doc["owner_id"] != user["id"]:
        raise ApiError(403, "forbidden", "Only the owner or an admin can manage collaborators.")
    for collaborator_id in set(payload.user_ids):
        if conn.execute("SELECT 1 FROM users WHERE id = ?", (collaborator_id,)).fetchone() is None:
            raise ApiError(404, "not_found", "Collaborator not found.")
        if collaborator_id != doc["owner_id"]:
            conn.execute("""INSERT INTO document_collaborators (document_id, user_id, access, added_by, added_at)
                            VALUES (?, ?, ?, ?, ?) ON CONFLICT(document_id, user_id) DO UPDATE SET access = excluded.access""", (document_id, collaborator_id, payload.access, user["id"], _now()))
    conn.commit()
    return {"collaborators": _document_collaborators(conn, document_id)}


@router.delete("/{document_id}/collaborators/{user_id}", status_code=204)
def remove_collaborator(document_id: str, user_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    access.require_visible_document(conn, user, document_id)
    doc = conn.execute("SELECT owner_id FROM documents WHERE id = ?", (document_id,)).fetchone()
    if user["role"] != "admin" and doc["owner_id"] != user["id"]:
        raise ApiError(403, "forbidden", "Only the owner or an admin can manage collaborators.")
    conn.execute("DELETE FROM document_collaborators WHERE document_id = ? AND user_id = ?", (document_id, user_id))
    conn.commit()
    return None


@router.patch("/{document_id}")
def patch_document(document_id: str, payload: DocumentPatch, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    access.require_document_write(conn, user, document_id)
    if payload.doc_type is not None and payload.doc_type not in _DOC_TYPES:
        raise ApiError(422, "validation_error", "Invalid document type.")
    if payload.owner_id is not None:
        doc = conn.execute("SELECT owner_id FROM documents WHERE id = ?", (document_id,)).fetchone()
        if user["role"] != "admin" and doc["owner_id"] != user["id"]:
            raise ApiError(403, "forbidden", "Only the owner or an admin can reassign a document.")
        if conn.execute("SELECT 1 FROM users WHERE id = ?", (payload.owner_id,)).fetchone() is None:
            raise ApiError(404, "not_found", "New owner not found.")
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    if updates:
        conn.execute("UPDATE documents SET " + ", ".join(f"{key} = ?" for key in updates) + " WHERE id = ?", [*updates.values(), document_id])
        conn.commit()
    return _document_detail(conn, document_id)


def _open_impacts_by_chunk(conn: sqlite3.Connection, document_id: str) -> dict[str, list[dict]]:
    """Still-open findings on this document, grouped by chunk, worst first.

    One query for the whole document. Severity is derived per impact (the
    parent change's effective date decides the critical escalation), so it
    cannot be a SQL MAX over `impact_level`.
    """
    open_clause, open_values = workflow.open_status_sql("i.review_status")
    rows = conn.execute(
        f"""SELECT i.id, i.document_chunk_id, i.impact_level, i.confidence, i.reason,
                   i.review_status, i.conflicting_span, i.conflicting_start, i.conflicting_end,
                   c.change_type, c.effective_date, c.source, c.summary AS change_summary
              FROM impacts i
              JOIN regulatory_changes c ON c.id = i.regulatory_change_id
             WHERE i.document_id = ? AND i.impact_level <> 'none' AND {open_clause}""",
        [document_id, *open_values],
    ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        item = dict(row)
        item["severity"] = severity_service.derive_severity(row, row)
        item["review_status_label"] = workflow.STATUS_LABELS.get(row["review_status"], row["review_status"])
        grouped.setdefault(row["document_chunk_id"], []).append(item)
    for items in grouped.values():
        items.sort(key=lambda entry: -severity_service.SEVERITY_RANK.get(entry["severity"], 0))
    return grouped


def _document_detail(conn: sqlite3.Connection, document_id: str) -> dict:
    doc = conn.execute("SELECT d.*, u.display_name AS owner_name FROM documents d JOIN users u ON u.id = d.owner_id WHERE d.id = ?", (document_id,)).fetchone()
    chunks = conn.execute("SELECT * FROM document_chunks WHERE document_id = ? ORDER BY ordinal", (document_id,)).fetchall()
    impacts_by_chunk = _open_impacts_by_chunk(conn, document_id)
    # Approved wording is an overlay the reader composes over the stored text.
    # `document_chunks.content` below is exactly what was uploaded — patching
    # never rewrites it (api/services/patching.py).
    patches = patching.patches_for_document(conn, document_id)
    patches_by_chunk: dict[str, list[dict]] = {}
    for patch in patches:
        patches_by_chunk.setdefault(patch["document_chunk_id"], []).append(patch)
    rendered = []
    for chunk in chunks:
        deps = conn.execute("""SELECT dep.*, l.public_ref FROM dependencies dep JOIN requirement_lineages l ON l.id = dep.lineage_id
                             WHERE dep.document_chunk_id = ? AND dep.status = 'active'""", (chunk["id"],)).fetchall()
        chunk_impacts = impacts_by_chunk.get(chunk["id"], [])
        rendered.append({
            **dict(chunk),
            # Same locator the review queue and review screen use.
            "clause_label": clauses.clause_label(chunk),
            "dependencies": [{key: dep[key] for key in ("lineage_id", "public_ref", "confidence", "relationship_type", "evidence_start", "evidence_end")} for dep in deps],
            "contributions": contributions.for_chunk(conn, chunk["id"]),
            "impacts": chunk_impacts,
            "severity": severity_service.max_severity(item["severity"] for item in chunk_impacts),
            "patches": patches_by_chunk.get(chunk["id"], []),
        })
    document = dict(doc)
    document["owner"] = {"id": doc["owner_id"], "display_name": doc["owner_name"]}
    document["collaborators"] = _document_collaborators(conn, document_id)
    document["contributors"] = contributions.for_document(conn, document_id)
    document["max_severity"] = severity_service.max_severity(
        chunk["severity"] for chunk in rendered
    )
    document["patch_count"] = len(patches)
    return {"document": document, "chunks": rendered, "patches": patches}


@router.get("/{document_id}")
def get_document(document_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    access.require_visible_document(conn, user, document_id)
    return _document_detail(conn, document_id)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    access.require_document_write(conn, user, document_id)
    row = conn.execute("SELECT file_path FROM documents WHERE id = ?", (document_id,)).fetchone()
    conn.execute("DELETE FROM fts_chunks WHERE chunk_id IN (SELECT id FROM document_chunks WHERE document_id = ?)", (document_id,))
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()
    storage.delete_file(row["file_path"])
    return None
