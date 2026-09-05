"""Visibility-scoped dependency graph data."""
from __future__ import annotations
import sqlite3
from typing import Literal
from fastapi import APIRouter, Depends
from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError

router = APIRouter(prefix="/graph", tags=["graph"])

@router.get("")
def get_graph(change_id: str | None = None, regulation_id: str | None = None, document_id: str | None = None, owner_id: str | None = None, min_confidence: float = 0, level: Literal["document", "section"] = "document", conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    if not 0 <= min_confidence <= 1:
        raise ApiError(422, "validation_error", "min_confidence must be between 0 and 1.")
    if level == "section" and not document_id and not change_id:
        raise ApiError(400, "bad_request", "A document_id or change_id is required for section level.")
    visible = access.visible_document_ids(conn, user)
    if document_id:
        access.require_visible_document(conn, user, document_id)
    where = ["d.document_id IN ({})".format(",".join("?" * len(visible)) if visible else "NULL"), "d.status='active'", "d.confidence >= ?"]
    values: list[object] = [*visible, min_confidence]
    if document_id: where.append("d.document_id=?"); values.append(document_id)
    if owner_id: where.append("doc.owner_id=?"); values.append(owner_id)
    if regulation_id: where.append("q.regulation_id=?"); values.append(regulation_id)
    rows = conn.execute("SELECT d.*, l.public_ref, q.requirement_text, q.subject, doc.name, doc.doc_type, doc.owner_id, u.display_name AS owner_name, c.section_path, c.page_number FROM dependencies d JOIN requirement_lineages l ON l.id=d.lineage_id JOIN regulatory_requirements q ON q.id=l.current_version_id JOIN documents doc ON doc.id=d.document_id JOIN users u ON u.id=doc.owner_id JOIN document_chunks c ON c.id=d.document_chunk_id WHERE " + " AND ".join(where), values).fetchall()
    impacted: dict[str, str] = {}
    if change_id:
        for row in conn.execute("SELECT document_id, impact_level FROM impacts WHERE regulatory_change_id=?", (change_id,)).fetchall():
            impacted[row["document_id"]] = row["impact_level"]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for row in rows:
        req_id = f"req:{row['lineage_id']}"
        nodes.setdefault(req_id, {"id": req_id, "kind": "requirement", "label": f"{row['public_ref']} · {row['subject'].replace('_', ' ')}", "state": "changed" if change_id else "current"})
        doc_id = f"doc:{row['document_id']}"
        state = f"affected_{impacted[row['document_id']]}" if row["document_id"] in impacted else "dependent_unaffected"
        nodes.setdefault(doc_id, {"id": doc_id, "kind": "document", "label": row["name"], "doc_type": row["doc_type"], "owner": row["owner_name"], "state": state})
        target = doc_id
        if level == "section":
            target = f"sec:{row['document_chunk_id']}"
            nodes.setdefault(target, {"id": target, "kind": "section", "parent": doc_id, "label": row["section_path"] or row["name"], "page": row["page_number"], "state": state})
        edges.append({
            "id": row["id"],
            "source": req_id,
            "target": target,
            "relationship_type": row["relationship_type"],
            "confidence": row["confidence"],
            "lineage_id": row["lineage_id"],
            "document_id": row["document_id"],
            "document_chunk_id": row["document_chunk_id"],
            "evidence_start": row["evidence_start"],
            "evidence_end": row["evidence_end"],
            "page_number": row["page_number"],
        })
    return {"nodes": list(nodes.values()), "edges": edges, "hidden_document_count": 0}
