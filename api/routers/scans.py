"""Corpus reconciliation for missing mapping and impact work."""
from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import impact, mapping

router = APIRouter(prefix="/scans", tags=["scans"])
def _now() -> str: return datetime.now(timezone.utc).isoformat()

class ScanCreate(BaseModel):
    scope: Literal["stale", "full", "document", "lineage"] = "stale"
    scope_id: str | None = None
    confirm: bool = False

def _gaps(conn: sqlite3.Connection, ids: set[str] | None = None) -> dict[str, int]:
    suffix, values = ("", []) if ids is None else (" AND d.id IN ({})".format(",".join("?" * len(ids)) if ids else "NULL"), list(ids))
    unmapped = conn.execute("SELECT COUNT(*) AS n FROM documents d CROSS JOIN requirement_lineages l LEFT JOIN mapping_passes p ON p.document_id=d.id AND p.lineage_id=l.id WHERE d.status='ready' AND p.document_id IS NULL" + suffix, values).fetchone()["n"]
    missing = conn.execute("SELECT COUNT(*) AS n FROM dependencies d JOIN regulatory_changes c ON c.lineage_id=d.lineage_id LEFT JOIN impacts i ON i.dependency_id=d.id AND i.regulatory_change_id=c.id WHERE d.status='active' AND i.id IS NULL").fetchone()["n"]
    orphaned = conn.execute("SELECT COUNT(*) AS n FROM dependencies d JOIN document_chunks c ON c.id=d.document_chunk_id WHERE d.status='active' AND d.evidence_span IS NOT NULL AND instr(c.content,d.evidence_span)=0").fetchone()["n"]
    return {"unmapped_pairs": unmapped, "unevaluated_impacts": missing, "orphaned_dependencies": orphaned, "restaled_mappings": 0}

@router.get("/pending")
def scans_pending(conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    running = conn.execute("SELECT id FROM scans WHERE status='running' ORDER BY created_at DESC LIMIT 1").fetchone()
    gaps = _gaps(conn, access.visible_document_ids(conn, user))
    return {"is_stale": any(gaps.values()), "gaps": gaps, "estimated_cost_usd": round(gaps["unmapped_pairs"] * 0.0002, 4), "running_scan_id": running["id"] if running else None}

@router.post("", status_code=202)
def create_scan(payload: ScanCreate, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    running = conn.execute("SELECT * FROM scans WHERE status='running' ORDER BY created_at DESC LIMIT 1").fetchone()
    if running: return {"scan_id": running["id"], "status": "running"}
    if payload.scope == "full" and user["role"] != "admin": raise ApiError(403, "forbidden", "A full re-scan requires an admin account.")
    if payload.scope == "full" and not payload.confirm: raise ApiError(422, "validation_error", "confirm must be true for a full re-scan.")
    sid = uuid.uuid4().hex; now = _now()
    conn.execute("INSERT INTO scans (id,trigger,scope,scope_id,initiated_by,status,started_at,finished_at,created_at) VALUES (?, 'manual', ?, ?, ?, 'running', ?, ?, ?)", (sid, payload.scope, payload.scope_id, user["id"], now, now, now))
    document_ids = access.visible_document_ids(conn, user)
    if payload.scope == "document" and payload.scope_id: document_ids = {payload.scope_id} & document_ids
    gaps = _gaps(conn, document_ids)
    added = 0
    for doc_id in document_ids:
        if payload.scope == "full" or conn.execute("SELECT 1 FROM mapping_passes WHERE document_id=? LIMIT 1", (doc_id,)).fetchone() is None:
            added += mapping.map_document(conn, doc_id, sid).dependencies_added
    changes = conn.execute("SELECT id FROM regulatory_changes WHERE analysis_status != 'complete'").fetchall()
    impacts_created = sum(impact.analyse_change(conn, row["id"]) for row in changes)
    conn.execute("UPDATE dependencies SET status='dismissed', rationale='Source text changed' WHERE evidence_span IS NOT NULL AND id IN (SELECT d.id FROM dependencies d JOIN document_chunks c ON c.id=d.document_chunk_id WHERE instr(c.content,d.evidence_span)=0)")
    conn.execute("UPDATE scans SET status='succeeded', documents_scanned=?, requirements_scanned=?, dependencies_added=?, impacts_created=?, finished_at=? WHERE id=?", (len(document_ids), gaps["unmapped_pairs"], added, impacts_created, _now(), sid)); conn.commit()
    return {"scan_id": sid}

@router.get("")
def list_scans(conn: sqlite3.Connection = Depends(get_db), _user: sqlite3.Row = Depends(get_current_user)):
    return {"items": [dict(row) for row in conn.execute("SELECT * FROM scans ORDER BY created_at DESC").fetchall()]}

@router.get("/{scan_id}")
def get_scan(scan_id: str, conn: sqlite3.Connection = Depends(get_db), _user: sqlite3.Row = Depends(get_current_user)):
    row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    if not row: raise ApiError(404, "not_found", "Scan not found.")
    return {"scan": dict(row)}
