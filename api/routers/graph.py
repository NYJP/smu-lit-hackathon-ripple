"""Visibility-scoped dependency graph data."""
from __future__ import annotations
import sqlite3
from typing import Literal
from fastapi import APIRouter, Depends
from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import contributions

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
    rows = conn.execute("SELECT d.*, l.public_ref, q.requirement_text, q.subject, r.title AS regulation_title, doc.name, doc.doc_type, doc.owner_id, u.display_name AS owner_name, c.section_path, c.page_number FROM dependencies d JOIN requirement_lineages l ON l.id=d.lineage_id JOIN regulatory_requirements q ON q.id=l.current_version_id JOIN regulations r ON r.id=q.regulation_id JOIN documents doc ON doc.id=d.document_id JOIN users u ON u.id=doc.owner_id JOIN document_chunks c ON c.id=d.document_chunk_id WHERE " + " AND ".join(where), values).fetchall()
    impact_filter = "i.regulatory_change_id = ?" if change_id else "i.review_status IN ('open', 'in_review')"
    impact_values: list[object] = [change_id] if change_id else []
    impact_rows = conn.execute(
        f"""SELECT i.*, rc.lineage_id, rc.summary AS change_summary
              FROM impacts i JOIN regulatory_changes rc ON rc.id=i.regulatory_change_id
             WHERE {impact_filter} AND i.document_id IN ({','.join('?' * len(visible)) if visible else 'NULL'})""",
        [*impact_values, *visible],
    ).fetchall()
    rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    impacts_by_dependency: dict[str, sqlite3.Row] = {}
    lineage_levels: dict[str, str] = {}
    document_levels: dict[str, str] = {}
    for impact_row in impact_rows:
        existing = impacts_by_dependency.get(impact_row["dependency_id"])
        if existing is None or rank[impact_row["impact_level"]] > rank[existing["impact_level"]]:
            impacts_by_dependency[impact_row["dependency_id"]] = impact_row
        if rank[impact_row["impact_level"]] > rank.get(lineage_levels.get(impact_row["lineage_id"], "none"), 0):
            lineage_levels[impact_row["lineage_id"]] = impact_row["impact_level"]
        if rank[impact_row["impact_level"]] > rank.get(document_levels.get(impact_row["document_id"], "none"), 0):
            document_levels[impact_row["document_id"]] = impact_row["impact_level"]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for row in rows:
        req_id = f"req:{row['lineage_id']}"
        requirement_level = lineage_levels.get(row["lineage_id"])
        nodes.setdefault(req_id, {"id": req_id, "kind": "requirement", "label": f"{row['public_ref']} · {row['subject'].replace('_', ' ')}", "requirement_text": row["requirement_text"], "regulation_title": row["regulation_title"], "state": f"affected_{requirement_level}" if requirement_level else "current", "impact_level": requirement_level})
        doc_id = f"doc:{row['document_id']}"
        document_level = document_levels.get(row["document_id"])
        state = f"affected_{document_level}" if document_level else "dependent_unaffected"
        nodes.setdefault(doc_id, {"id": doc_id, "kind": "document", "label": row["name"], "doc_type": row["doc_type"], "owner": row["owner_name"], "state": state, "impact_level": document_level})
        target = doc_id
        if level == "section":
            target = f"sec:{row['document_chunk_id']}"
            nodes.setdefault(target, {"id": target, "kind": "section", "parent": doc_id, "label": row["section_path"] or row["name"], "page": row["page_number"], "state": state})
        edge_impact = impacts_by_dependency.get(row["id"])
        contributor = contributions.for_span(
            conn,
            row["document_chunk_id"],
            edge_impact["conflicting_start"] if edge_impact else row["evidence_start"],
            edge_impact["conflicting_end"] if edge_impact else row["evidence_end"],
        )
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
            "impact_level": edge_impact["impact_level"] if edge_impact else None,
            "impact_reason": edge_impact["reason"] if edge_impact else None,
            "change_summary": edge_impact["change_summary"] if edge_impact else None,
            "affected_start": edge_impact["conflicting_start"] if edge_impact else None,
            "affected_end": edge_impact["conflicting_end"] if edge_impact else None,
            "contributor": contributor,
        })
    return {"nodes": list(nodes.values()), "edges": edges, "hidden_document_count": 0}
