"""Dependency read/write endpoints (PRD section 9.5)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import mapping

router = APIRouter(prefix="/dependencies", tags=["dependencies"])

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DependencyCreate(BaseModel):
    lineage_id: str = Field(min_length=1)
    document_chunk_id: str = Field(min_length=1)
    relationship_type: Literal["restates", "implements", "references", "defines"]
    evidence_span: str | None = None


class DependencyPatch(BaseModel):
    status: Literal["dismissed"]


def _visible_dependency(conn: sqlite3.Connection, user: sqlite3.Row, dependency_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM dependencies WHERE id = ?", (dependency_id,)).fetchone()
    if row is None or not access.is_document_visible(conn, user, row["document_id"]):
        raise ApiError(404, "not_found", "Dependency not found.")
    return row


@router.get("")
def list_dependencies(
    lineage_id: str | None = None,
    document_id: str | None = None,
    min_confidence: float | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    if min_confidence is not None and not 0 <= min_confidence <= 1:
        raise ApiError(422, "validation_error", "min_confidence must be between 0 and 1.")
    if lineage_id is not None and conn.execute("SELECT 1 FROM requirement_lineages WHERE id = ?", (lineage_id,)).fetchone() is None:
        raise ApiError(404, "not_found", "Requirement not found.")
    if document_id is not None:
        access.require_visible_document(conn, user, document_id)
    visible = access.visible_document_ids(conn, user)
    if not visible:
        return {"items": []}
    filters = [f"d.document_id IN ({','.join('?' * len(visible))})", "d.status = 'active'"]
    values: list[object] = [*visible]
    if lineage_id is not None:
        filters.append("d.lineage_id = ?")
        values.append(lineage_id)
    if document_id is not None:
        filters.append("d.document_id = ?")
        values.append(document_id)
    if min_confidence is not None:
        filters.append("d.confidence >= ?")
        values.append(min_confidence)
    rows = conn.execute(
        f"""SELECT d.*, l.public_ref, c.content AS chunk_content, c.section_path, c.page_number,
                    doc.name AS document_name
             FROM dependencies d
             JOIN requirement_lineages l ON l.id = d.lineage_id
             JOIN document_chunks c ON c.id = d.document_chunk_id
             JOIN documents doc ON doc.id = d.document_id
             WHERE {' AND '.join(filters)}
             ORDER BY d.created_at DESC, d.id DESC""",
        values,
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("", status_code=201)
def create_dependency(
    payload: DependencyCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    if conn.execute("SELECT 1 FROM requirement_lineages WHERE id = ?", (payload.lineage_id,)).fetchone() is None:
        raise ApiError(404, "not_found", "Requirement not found.")
    chunk = conn.execute("SELECT * FROM document_chunks WHERE id = ?", (payload.document_chunk_id,)).fetchone()
    if chunk is None:
        raise ApiError(404, "not_found", "Document chunk not found.")
    access.require_document_write(conn, user, chunk["document_id"])
    evidence_span, evidence_start, evidence_end = mapping._locate_span(chunk["content"], payload.evidence_span)
    existing = conn.execute("SELECT * FROM dependencies WHERE lineage_id = ? AND document_chunk_id = ?", (payload.lineage_id, chunk["id"])).fetchone()
    if existing is None:
        dependency_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO dependencies (id, lineage_id, document_chunk_id, document_id, relationship_type, confidence, rationale, evidence_span, evidence_start, evidence_end, created_at)
               VALUES (?, ?, ?, ?, ?, 1.0, 'Added manually', ?, ?, ?, ?)""",
            (dependency_id, payload.lineage_id, chunk["id"], chunk["document_id"], payload.relationship_type, evidence_span, evidence_start, evidence_end, _now()),
        )
    else:
        dependency_id = existing["id"]
        conn.execute(
            """UPDATE dependencies SET relationship_type = ?, confidence = 1.0, rationale = 'Added manually', evidence_span = ?, evidence_start = ?, evidence_end = ?, status = 'active' WHERE id = ?""",
            (payload.relationship_type, evidence_span, evidence_start, evidence_end, dependency_id),
        )
    conn.commit()
    return dict(conn.execute("SELECT * FROM dependencies WHERE id = ?", (dependency_id,)).fetchone())


@router.patch("/{dependency_id}")
def patch_dependency(
    dependency_id: str,
    payload: DependencyPatch,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    dependency = _visible_dependency(conn, user, dependency_id)
    access.require_document_write(conn, user, dependency["document_id"])
    conn.execute("UPDATE dependencies SET status = ? WHERE id = ?", (payload.status, dependency_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM dependencies WHERE id = ?", (dependency_id,)).fetchone())
