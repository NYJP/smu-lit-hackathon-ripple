"""What-if simulations backed by the shared change and impact model."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from api.auth import get_current_user
from api.db import get_connection, get_db
from api.errors import ApiError
from api.services import clauses, jobs, severity as severity_service, simulations as simulation_service

router = APIRouter(prefix="/simulations", tags=["simulations"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Edit(BaseModel):
    lineage_id: str | None = None
    op: Literal["modify", "repeal", "add"] = "modify"
    proposed_requirement_text: str | None = None
    proposed_value: str | None = None
    proposed_value_numeric: float | None = None
    proposed_value_unit: str | None = None
    proposed_comparator: str | None = None
    proposed_condition: str | None = None
    proposed_exception: str | None = None
    proposed_effective_date: str | None = None


class SimulationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    note: str | None = None
    edits: list[Edit] = Field(min_length=1)

class SimulationPatch(BaseModel):
    name: str | None = None
    note: str | None = None
    edits: list[Edit] | None = None


def _require(conn: sqlite3.Connection, simulation_id: str, user: sqlite3.Row) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM simulations WHERE id = ?", (simulation_id,)).fetchone()
    if row is None or (row["created_by"] != user["id"] and user["role"] != "admin"):
        raise ApiError(404, "not_found", "Simulation not found.")
    return row


def _save_edits(conn: sqlite3.Connection, simulation_id: str, edits: list[Edit]) -> None:
    for edit in edits:
        if edit.op != "add" and not edit.lineage_id:
            raise ApiError(422, "validation_error", "A requirement is required for this edit.")
        if edit.lineage_id and conn.execute("SELECT 1 FROM requirement_lineages WHERE id = ?", (edit.lineage_id,)).fetchone() is None:
            raise ApiError(404, "not_found", "Requirement not found.")
        conn.execute("INSERT INTO simulation_edits (id, simulation_id, lineage_id, op, proposed_requirement_text, proposed_value, proposed_value_numeric, proposed_value_unit, proposed_comparator, proposed_condition, proposed_exception, proposed_effective_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (uuid.uuid4().hex, simulation_id, edit.lineage_id, edit.op, edit.proposed_requirement_text, edit.proposed_value, edit.proposed_value_numeric, edit.proposed_value_unit, edit.proposed_comparator, edit.proposed_condition, edit.proposed_exception, edit.proposed_effective_date, _now()))


@router.post("", status_code=201)
def create_simulation(payload: SimulationCreate, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    sid = uuid.uuid4().hex
    now = _now()
    conn.execute("INSERT INTO simulations (id, created_by, name, note, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', ?, ?)", (sid, user["id"], payload.name, payload.note, now, now))
    _save_edits(conn, sid, payload.edits)
    conn.commit()
    return {"simulation_id": sid}


@router.get("")
def list_simulations(conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    rows = conn.execute("""SELECT s.*, COUNT(DISTINCT e.id) AS edit_count,
      COUNT(DISTINCT CASE WHEN i.impact_level!='none' THEN i.document_id END) AS affected_document_count,
      COUNT(DISTINCT CASE WHEN i.impact_level='high' THEN i.id END) AS high,
      COUNT(DISTINCT CASE WHEN i.impact_level='medium' THEN i.id END) AS medium,
      COUNT(DISTINCT CASE WHEN i.impact_level='low' THEN i.id END) AS low
      FROM simulations s LEFT JOIN simulation_edits e ON e.simulation_id=s.id
      LEFT JOIN regulatory_changes c ON c.simulation_id=s.id LEFT JOIN impacts i ON i.regulatory_change_id=c.id
      WHERE s.created_by=? OR ?='admin' GROUP BY s.id ORDER BY s.created_at DESC""", (user["id"], user["role"])).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/{simulation_id}")
def get_simulation(simulation_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    simulation = _require(conn, simulation_id, user)
    edits = conn.execute("""SELECT e.*, l.public_ref, q.requirement_text AS current_requirement_text,
        q.value AS current_value FROM simulation_edits e
        LEFT JOIN requirement_lineages l ON l.id=e.lineage_id
        LEFT JOIN regulatory_requirements q ON q.id=l.current_version_id
        WHERE e.simulation_id=? ORDER BY e.created_at, e.id""", (simulation_id,)).fetchall()
    changes = conn.execute("""SELECT c.*, l.public_ref,
        COUNT(i.id) AS impact_count,
        COUNT(DISTINCT CASE WHEN i.impact_level!='none' THEN i.document_id END) AS affected_document_count
        FROM regulatory_changes c LEFT JOIN requirement_lineages l ON l.id=c.lineage_id
        LEFT JOIN impacts i ON i.regulatory_change_id=c.id WHERE c.simulation_id=? GROUP BY c.id""", (simulation_id,)).fetchall()
    impact_rows = conn.execute("""SELECT i.*, d.name AS document_name, ch.section_path, ch.page_number,
        c.summary AS change_summary, l.public_ref
        FROM impacts i JOIN regulatory_changes c ON c.id=i.regulatory_change_id
        JOIN documents d ON d.id=i.document_id JOIN document_chunks ch ON ch.id=i.document_chunk_id
        LEFT JOIN requirement_lineages l ON l.id=c.lineage_id
        WHERE c.simulation_id=? ORDER BY i.confidence DESC""", (simulation_id,)).fetchall()
    counts = {level: 0 for level in ("high", "medium", "low", "none")}
    impacts = []
    for row in impact_rows:
        counts[row["impact_level"]] += 1
        item = dict(row)
        item["severity"] = severity_service.derive_severity(row, row)
        chunk = conn.execute("SELECT * FROM document_chunks WHERE id=?", (row["document_chunk_id"],)).fetchone()
        item["clause_label"] = clauses.clause_label(chunk, position=row["conflicting_start"]) if chunk else "Affected clause"
        impacts.append(item)
    affected = len({row["document_id"] for row in impact_rows if row["impact_level"] != "none"})
    examined = conn.execute("""SELECT COUNT(DISTINCT d.document_id) AS n FROM dependencies d
        JOIN simulation_edits e ON e.lineage_id=d.lineage_id WHERE e.simulation_id=? AND d.status='active'""", (simulation_id,)).fetchone()["n"]
    return {"simulation": dict(simulation), "edits": [dict(row) for row in edits], "changes": [dict(row) for row in changes],
            "impacts": impacts, "totals": {**counts, "documents_examined": examined,
            "affected_documents": affected, "likely_unaffected": max(0, examined - affected)}}


@router.patch("/{simulation_id}")
def patch_simulation(simulation_id: str, payload: SimulationPatch, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    _require(conn, simulation_id, user)
    if payload.name is not None:
        conn.execute("UPDATE simulations SET name=? WHERE id=?", (payload.name, simulation_id))
    if payload.note is not None:
        conn.execute("UPDATE simulations SET note=? WHERE id=?", (payload.note, simulation_id))
    if payload.edits is not None:
        conn.execute("DELETE FROM regulatory_changes WHERE simulation_id=?", (simulation_id,))
        conn.execute("DELETE FROM simulation_edits WHERE simulation_id=?", (simulation_id,))
        _save_edits(conn, simulation_id, payload.edits)
        conn.execute("UPDATE simulations SET status='draft' WHERE id=?", (simulation_id,))
    conn.execute("UPDATE simulations SET updated_at=? WHERE id=?", (_now(), simulation_id))
    conn.commit()
    return get_simulation(simulation_id, conn, user)


@router.post("/{simulation_id}/estimate")
def estimate_simulation(simulation_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    _require(conn, simulation_id, user)
    return simulation_service.estimate(conn, simulation_id)


@router.post("/{simulation_id}/run", status_code=202)
def run_simulation(simulation_id: str, background_tasks: BackgroundTasks, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    _require(conn, simulation_id, user)
    job_id = jobs.create_job(conn, "simulation_run", "simulation", simulation_id,
                             initiated_by=user["id"], input_payload={"simulation_id": simulation_id})
    jobs.run_job(background_tasks, get_connection, job_id, simulation_service.run_simulation_job)
    return {"simulation_id": simulation_id, "job_id": job_id}


@router.post("/{simulation_id}/promote")
def promote_simulation(simulation_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    simulation = _require(conn, simulation_id, user)
    if user["role"] != "admin":
        raise ApiError(403, "forbidden", "An admin account is required to promote a simulation.")
    if simulation["status"] != "complete":
        raise ApiError(409, "conflict", "Run the simulation before promoting it.")
    promoted: list[dict] = []
    changes = conn.execute("SELECT * FROM regulatory_changes WHERE simulation_id=?", (simulation_id,)).fetchall()
    for change in changes:
        if not change["lineage_id"] or change["change_type"] == "removed":
            continue
        previous = conn.execute("SELECT * FROM regulatory_requirements WHERE id=?", (change["previous_requirement_id"],)).fetchone()
        snapshot = json.loads(change["proposed_snapshot"] or "{}")
        requirement_id = uuid.uuid4().hex
        conn.execute("UPDATE regulatory_requirements SET is_current=0, superseded_by=? WHERE id=?", (requirement_id, previous["id"]))
        conn.execute("INSERT INTO regulatory_requirements (id,lineage_id,regulation_id,version,requirement_text,verbatim_text,requirement_type,subject,value,value_numeric,value_unit,comparator,condition,exception,source_section,source_page,effective_date,origin,is_current,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'manual',1,?)", (requirement_id,previous["lineage_id"],previous["regulation_id"],previous["version"] + 1,snapshot.get("requirement_text",previous["requirement_text"]),previous["verbatim_text"],previous["requirement_type"],snapshot.get("subject",previous["subject"]),snapshot.get("value",previous["value"]),snapshot.get("value_numeric",previous["value_numeric"]),snapshot.get("value_unit",previous["value_unit"]),snapshot.get("comparator",previous["comparator"]),snapshot.get("condition",previous["condition"]),snapshot.get("exception",previous["exception"]),snapshot.get("source_section",previous["source_section"]),previous["source_page"],snapshot.get("effective_date",previous["effective_date"]),_now()))
        conn.execute("UPDATE requirement_lineages SET current_version_id=? WHERE id=?", (requirement_id, previous["lineage_id"]))
        conn.execute("UPDATE regulatory_changes SET source='manual', simulation_id=NULL, new_requirement_id=?, proposed_snapshot=NULL WHERE id=?", (requirement_id, change["id"]))
        promoted.append({"change_id": change["id"], "requirement_id": requirement_id})
    conn.execute("UPDATE simulations SET status='promoted', updated_at=? WHERE id=?", (_now(), simulation_id))
    conn.commit()
    return {"changes": promoted}


@router.delete("/{simulation_id}", status_code=204)
def delete_simulation(simulation_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    _require(conn, simulation_id, user)
    conn.execute("DELETE FROM simulations WHERE id=?", (simulation_id,))
    conn.commit()
