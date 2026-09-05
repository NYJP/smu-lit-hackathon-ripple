"""Extracted requirement readback (section 9.2).

`PATCH /requirements/{lineage_id}` writes a requirement lineage/version, so
it is admin-only per the resource matrix; reads and the simulate shorthand
are open to every signed-in member.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api import access
from api.access import require_admin
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import impact

router = APIRouter(prefix="/requirements", tags=["requirements"])

class RequirementPatch(BaseModel):
    requirement_text: str | None = None
    value: str | None = None
    value_numeric: float | None = None
    value_unit: str | None = None
    comparator: str | None = None
    condition: str | None = None
    exception: str | None = None
    subject: str | None = None
    source_section: str | None = None
    effective_date: str | None = None
    propagate: bool = False

@router.get("")
def list_requirements(
    regulation_id: str | None = None,
    requirement_type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    if not 1 <= limit <= 200:
        raise ApiError(422, "validation_error", "limit must be between 1 and 200.")
    visible = access.visible_document_ids(conn, user)
    dependency_scope = "0 = 1" if not visible else f"d.document_id IN ({','.join('?' * len(visible))})"
    rows = conn.execute(
        """SELECT q.*, l.public_ref,
                  (SELECT COUNT(*) FROM dependencies d WHERE d.lineage_id = l.id AND d.status = 'active' AND """ + dependency_scope + """) AS dependency_count
           FROM regulatory_requirements q JOIN requirement_lineages l ON l.id = q.lineage_id
           WHERE q.is_current = 1
             AND (? IS NULL OR q.regulation_id = ?)
             AND (? IS NULL OR q.requirement_type = ?)
             AND (? IS NULL OR q.requirement_text LIKE '%' || ? || '%' OR q.subject LIKE '%' || ? || '%')
             AND (? IS NULL OR q.created_at < ?)
           ORDER BY q.created_at DESC, q.id DESC LIMIT ?""",
        [*visible, regulation_id, regulation_id, requirement_type, requirement_type, q, q, q, cursor, cursor, limit + 1] if visible else (regulation_id, regulation_id, requirement_type, requirement_type, q, q, q, cursor, cursor, limit + 1),
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
            f"""SELECT d.id AS dependency_id, d.document_id, d.document_chunk_id, doc.name AS document_name, c.section_path, c.page_number,
                       c.content AS excerpt, d.evidence_span, d.evidence_start, d.evidence_end, d.relationship_type, d.confidence
                FROM dependencies d JOIN documents doc ON doc.id = d.document_id JOIN document_chunks c ON c.id = d.document_chunk_id
                WHERE d.lineage_id = ? AND d.status = 'active' AND d.document_id IN ({placeholders})""",
            [lineage_id, *visible],
        ).fetchall()
        dependencies = [dict(row) for row in rows]
    current = next((row for row in versions if row["id"] == lineage["current_version_id"]), None)
    return {"lineage": dict(lineage), "current_version": dict(current) if current else None, "versions": [dict(row) for row in versions], "dependencies": dependencies}


@router.patch("/{lineage_id}")
def patch_requirement(lineage_id: str, payload: RequirementPatch, conn: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(require_admin)):
    previous = conn.execute("SELECT q.* FROM requirement_lineages l JOIN regulatory_requirements q ON q.id=l.current_version_id WHERE l.id=?", (lineage_id,)).fetchone()
    if previous is None:
        raise ApiError(404, "not_found", "Requirement not found.")
    data = dict(previous)
    fields = ("requirement_text", "value", "value_numeric", "value_unit", "comparator", "condition", "exception", "subject", "source_section", "effective_date")
    for field in fields:
        value = getattr(payload, field)
        if value is not None:
            data[field] = value
    requirement_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE regulatory_requirements SET is_current=0, superseded_by=? WHERE id=?", (requirement_id, previous["id"]))
    conn.execute("INSERT INTO regulatory_requirements (id,lineage_id,regulation_id,version,requirement_text,verbatim_text,requirement_type,subject,value,value_numeric,value_unit,comparator,condition,exception,source_section,source_page,effective_date,origin,is_current,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'manual',1,?)", (requirement_id,lineage_id,previous["regulation_id"],previous["version"]+1,data["requirement_text"],previous["verbatim_text"],previous["requirement_type"],data["subject"],data["value"],data["value_numeric"],data["value_unit"],data["comparator"],data["condition"],data["exception"],data["source_section"],previous["source_page"],data["effective_date"],now))
    conn.execute("UPDATE requirement_lineages SET current_version_id=?, subject=? WHERE id=?", (requirement_id, data["subject"], lineage_id))
    change_id = None
    if payload.propagate:
        change_type, old_value, new_value, summary = impact.change_fields(previous, data)
        if change_type != "editorial":
            change_id = uuid.uuid4().hex
            conn.execute("INSERT INTO regulatory_changes (id,lineage_id,source,previous_requirement_id,new_requirement_id,change_type,old_value,new_value,summary,source_section,effective_date,analysis_status,created_at) VALUES (?,?, 'manual',?,?,?,?,?,?,?,?, 'pending',?)", (change_id,lineage_id,previous["id"],requirement_id,change_type,old_value,new_value,summary,data["source_section"],data["effective_date"],now))
    conn.commit()
    if change_id:
        impact.analyse_change(conn, change_id)
    return {"requirement": dict(conn.execute("SELECT * FROM regulatory_requirements WHERE id=?", (requirement_id,)).fetchone()), "change_id": change_id, "job_id": None}


@router.post("/{lineage_id}/simulate", status_code=202)
def simulate_requirement(lineage_id: str, payload: RequirementPatch, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    if conn.execute("SELECT 1 FROM requirement_lineages WHERE id=?", (lineage_id,)).fetchone() is None:
        raise ApiError(404, "not_found", "Requirement not found.")
    simulation_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO simulations (id,created_by,name,status,created_at,updated_at) VALUES (?,?,?,'draft',?,?)", (simulation_id,user["id"],"Requirement what-if",now,now))
    conn.execute("INSERT INTO simulation_edits (id,simulation_id,lineage_id,op,proposed_requirement_text,proposed_value,proposed_value_numeric,proposed_value_unit,proposed_comparator,proposed_condition,proposed_exception,proposed_effective_date,created_at) VALUES (?,?,?,'modify',?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex,simulation_id,lineage_id,payload.requirement_text,payload.value,payload.value_numeric,payload.value_unit,payload.comparator,payload.condition,payload.exception,payload.effective_date,now))
    conn.commit()
    from api.routers.simulations import run_simulation
    run_simulation(simulation_id, conn, user)
    return {"simulation_id": simulation_id, "job_id": None}
