"""What-if simulations backed by the shared change and impact model."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import impact

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
    rows = conn.execute("SELECT s.*, COUNT(e.id) AS edit_count FROM simulations s LEFT JOIN simulation_edits e ON e.simulation_id=s.id WHERE s.created_by=? OR ?='admin' GROUP BY s.id ORDER BY s.created_at DESC", (user["id"], user["role"])).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/{simulation_id}")
def get_simulation(simulation_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    simulation = _require(conn, simulation_id, user)
    edits = conn.execute("SELECT * FROM simulation_edits WHERE simulation_id=?", (simulation_id,)).fetchall()
    changes = conn.execute("SELECT c.*, l.public_ref FROM regulatory_changes c LEFT JOIN requirement_lineages l ON l.id=c.lineage_id WHERE c.simulation_id=?", (simulation_id,)).fetchall()
    return {"simulation": dict(simulation), "edits": [dict(row) for row in edits], "changes": [dict(row) for row in changes]}


@router.post("/{simulation_id}/estimate")
def estimate_simulation(simulation_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    _require(conn, simulation_id, user)
    count = conn.execute("SELECT COUNT(*) AS n FROM dependencies d JOIN simulation_edits e ON e.lineage_id=d.lineage_id WHERE e.simulation_id=? AND d.status='active'", (simulation_id,)).fetchone()["n"]
    return {"dependency_count": count, "cached_count": 0, "estimated_cost_usd": round(count * 0.0002, 4)}


@router.post("/{simulation_id}/run", status_code=202)
def run_simulation(simulation_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    _require(conn, simulation_id, user)
    conn.execute("DELETE FROM regulatory_changes WHERE simulation_id=?", (simulation_id,))
    edits = conn.execute("SELECT * FROM simulation_edits WHERE simulation_id=?", (simulation_id,)).fetchall()
    for edit in edits:
        previous = conn.execute("SELECT q.* FROM requirement_lineages l JOIN regulatory_requirements q ON q.id=l.current_version_id WHERE l.id=?", (edit["lineage_id"],)).fetchone() if edit["lineage_id"] else None
        proposed = dict(previous) if previous else {"subject": "new requirement", "value": None}
        for key in ("requirement_text", "value", "value_numeric", "value_unit", "comparator", "condition", "exception", "effective_date"):
            value = edit[f"proposed_{key}"]
            if value is not None:
                proposed[key] = value
        change_type, old_value, new_value, summary = impact.change_fields(previous, proposed, edit["op"])
        if change_type == "editorial":
            continue
        change_id = uuid.uuid4().hex
        conn.execute("INSERT INTO regulatory_changes (id,lineage_id,source,simulation_id,previous_requirement_id,proposed_snapshot,change_type,old_value,new_value,summary,source_section,effective_date,analysis_status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'pending',?)", (change_id, edit["lineage_id"], "simulation", simulation_id, previous["id"] if previous else None, json.dumps(proposed), change_type, old_value, new_value, summary, proposed.get("source_section"), proposed.get("effective_date"), _now()))
        if previous:
            impact.analyse_change(conn, change_id)
    conn.execute("UPDATE simulations SET status='complete', updated_at=? WHERE id=?", (_now(), simulation_id))
    conn.commit()
    return {"simulation_id": simulation_id}


@router.delete("/{simulation_id}", status_code=204)
def delete_simulation(simulation_id: str, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    _require(conn, simulation_id, user)
    conn.execute("DELETE FROM simulations WHERE id=?", (simulation_id,))
    conn.commit()
