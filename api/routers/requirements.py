"""Extracted requirement readback (section 9.2).

`PATCH /requirements/{lineage_id}` writes a requirement lineage/version, so
it is admin-only per the resource matrix; reads and the simulate shorthand
are open to every signed-in member.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api import access
from api.access import require_admin
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError, not_implemented

router = APIRouter(prefix="/requirements", tags=["requirements"])

@router.get("")
def list_requirements(
    regulation_id: str | None = None,
    requirement_type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    if not 1 <= limit <= 200:
        raise ApiError(422, "validation_error", "limit must be between 1 and 200.")
    rows = conn.execute(
        """SELECT q.*, l.public_ref,
                  (SELECT COUNT(*) FROM dependencies d WHERE d.lineage_id = l.id AND d.status = 'active') AS dependency_count
           FROM regulatory_requirements q JOIN requirement_lineages l ON l.id = q.lineage_id
           WHERE q.is_current = 1
             AND (? IS NULL OR q.regulation_id = ?)
             AND (? IS NULL OR q.requirement_type = ?)
             AND (? IS NULL OR q.requirement_text LIKE '%' || ? || '%' OR q.subject LIKE '%' || ? || '%')
             AND (? IS NULL OR q.created_at < ?)
           ORDER BY q.created_at DESC, q.id DESC LIMIT ?""",
        (regulation_id, regulation_id, requirement_type, requirement_type, q, q, q, cursor, cursor, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [{key: row[key] for key in ("lineage_id", "public_ref", "requirement_text", "requirement_type", "subject", "value", "source_section", "version", "dependency_count")} for row in rows],
        "next_cursor": rows[-1]["created_at"] if more else None,
    }


@router.get("/{lineage_id}")
def get_requirement(
    lineage_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    lineage = conn.execute("SELECT * FROM requirement_lineages WHERE id = ?", (lineage_id,)).fetchone()
    if lineage is None:
        raise ApiError(404, "not_found", "Requirement not found.")
    versions = conn.execute("SELECT * FROM regulatory_requirements WHERE lineage_id = ? ORDER BY version DESC", (lineage_id,)).fetchall()
    visible = access.visible_document_ids(conn, user)
    dependencies: list[dict] = []
    if visible:
        placeholders = ",".join("?" * len(visible))
        rows = conn.execute(
            f"""SELECT d.id AS dependency_id, d.document_id, doc.name AS document_name, c.section_path, c.page_number,
                       c.content AS excerpt, d.evidence_span, d.evidence_start, d.evidence_end, d.relationship_type, d.confidence
                FROM dependencies d JOIN documents doc ON doc.id = d.document_id JOIN document_chunks c ON c.id = d.document_chunk_id
                WHERE d.lineage_id = ? AND d.status = 'active' AND d.document_id IN ({placeholders})""",
            [lineage_id, *visible],
        ).fetchall()
        dependencies = [dict(row) for row in rows]
    current = next((row for row in versions if row["id"] == lineage["current_version_id"]), None)
    return {"lineage": dict(lineage), "current_version": dict(current) if current else None, "versions": [dict(row) for row in versions], "dependencies": dependencies}


@router.patch("/{lineage_id}")
def patch_requirement(lineage_id: str, _admin: sqlite3.Row = Depends(require_admin)):
    not_implemented("a later requirement authoring wave")


@router.post("/{lineage_id}/simulate", status_code=202)
def simulate_requirement(lineage_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented("the impact engine wave (build order step 7)")
