"""Capped, filterable dependency graph data."""
from __future__ import annotations

import sqlite3
from typing import Literal
from fastapi import APIRouter, Depends, Query

from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import contributions, severity as severity_service, workflow

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("")
def get_graph(
    change_id: str | None = None, regulation_id: str | None = None,
    document_id: str | None = None, owner_id: str | None = None,
    min_confidence: float = 0, level: Literal["document", "section"] = "document",
    limit: int = Query(250, ge=1, le=250),
    seed: Literal["changes", "mine", "all"] = "changes",
    severity: Literal["critical", "high", "medium", "low", "none"] | None = None,
    team_id: str | None = None, review_status: str | None = None,
    simulation_id: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    if not 0 <= min_confidence <= 1:
        raise ApiError(422, "validation_error", "min_confidence must be between 0 and 1.")
    if level == "section" and not document_id and not change_id:
        raise ApiError(400, "bad_request", "A document_id or change_id is required for section level.")
    if review_status and review_status not in workflow.ALLOWED_TRANSITIONS:
        raise ApiError(422, "validation_error", "Unknown review_status.")
    visible = access.visible_document_ids(conn, user)
    if document_id:
        access.require_visible_document(conn, user, document_id)

    impact_where = [f"i.document_id IN ({','.join('?' * len(visible)) if visible else 'NULL'})"]
    impact_values: list[object] = [*visible]
    open_clause, open_values = workflow.open_status_sql("i.review_status")
    if change_id:
        impact_where.append("i.regulatory_change_id=?"); impact_values.append(change_id)
    elif review_status:
        impact_where.append("i.review_status=?"); impact_values.append(review_status)
    else:
        impact_where.append(open_clause); impact_values.extend(open_values)
    if simulation_id:
        impact_where.append("rc.simulation_id=?"); impact_values.append(simulation_id)
    if severity:
        impact_where.append("i.impact_level=?"); impact_values.append("high" if severity == "critical" else severity)
    impact_rows = conn.execute(
        f"""SELECT i.*, rc.lineage_id, rc.summary change_summary, rc.change_type,
                   rc.effective_date, rc.source change_source, rc.simulation_id
              FROM impacts i JOIN regulatory_changes rc ON rc.id=i.regulatory_change_id
             WHERE {' AND '.join(impact_where)}""", impact_values).fetchall()
    if severity:
        impact_rows = [r for r in impact_rows if severity_service.derive_severity(r, r) == severity]

    rank = severity_service.SEVERITY_RANK
    impacts: dict[str, sqlite3.Row] = {}
    edge_levels: dict[str, str] = {}
    lineage_levels: dict[str, str] = {}
    document_levels: dict[str, str] = {}
    for impact in impact_rows:
        derived = severity_service.derive_severity(impact, impact)
        dep_id = impact["dependency_id"]
        if rank[derived] > rank.get(edge_levels.get(dep_id, "none"), 0):
            impacts[dep_id], edge_levels[dep_id] = impact, derived
        if rank[derived] > rank.get(lineage_levels.get(impact["lineage_id"], "none"), 0):
            lineage_levels[impact["lineage_id"]] = derived
        if rank[derived] > rank.get(document_levels.get(impact["document_id"], "none"), 0):
            document_levels[impact["document_id"]] = derived

    where = [f"d.document_id IN ({','.join('?' * len(visible)) if visible else 'NULL'})", "d.status='active'", "d.confidence>=?"]
    values: list[object] = [*visible, min_confidence]
    for clause, value in (("d.document_id=?", document_id), ("doc.owner_id=?", owner_id), ("q.regulation_id=?", regulation_id)):
        if value:
            where.append(clause); values.append(value)
    if team_id:
        where.append("EXISTS(SELECT 1 FROM document_teams dt WHERE dt.document_id=d.document_id AND dt.team_id=?)"); values.append(team_id)
    if seed == "mine":
        where.append("""(doc.owner_id=? OR EXISTS(SELECT 1 FROM document_collaborators dc WHERE dc.document_id=doc.id AND dc.user_id=?) OR EXISTS(SELECT 1 FROM follows f WHERE f.document_id=doc.id AND f.user_id=?) OR EXISTS(SELECT 1 FROM document_teams dt JOIN team_members tm ON tm.team_id=dt.team_id WHERE dt.document_id=doc.id AND tm.user_id=?))""")
        values.extend([user["id"]] * 4)
    filtered = sorted(impacts)
    if seed == "changes" or change_id or severity or review_status or simulation_id:
        if not filtered:
            return {"nodes": [], "edges": [], "hidden_document_count": 0, "truncated": {"nodes_omitted": 0, "edges_omitted": 0}}
        where.append(f"d.id IN ({','.join('?' * len(filtered))})"); values.extend(filtered)

    rows = conn.execute(f"""SELECT d.*, l.public_ref, q.requirement_text, q.subject,
      r.title regulation_title, doc.name, doc.doc_type, doc.owner_id, u.display_name owner_name,
      c.section_path, c.page_number FROM dependencies d
      JOIN requirement_lineages l ON l.id=d.lineage_id
      JOIN regulatory_requirements q ON q.id=l.current_version_id
      JOIN regulations r ON r.id=q.regulation_id JOIN documents doc ON doc.id=d.document_id
      JOIN users u ON u.id=doc.owner_id JOIN document_chunks c ON c.id=d.document_chunk_id
      WHERE {' AND '.join(where)} ORDER BY d.confidence DESC,d.id""", values).fetchall()

    chosen: list[sqlite3.Row] = []
    chosen_ids: set[str] = set()
    for row in rows:
        ids = {f"req:{row['lineage_id']}", f"doc:{row['document_id']}"}
        if level == "section": ids.add(f"sec:{row['document_chunk_id']}")
        if len(chosen_ids | ids) <= limit:
            chosen.append(row); chosen_ids |= ids
    dependency_counts: dict[str, int] = {}
    for row in rows:
        dependency_counts[row["document_id"]] = dependency_counts.get(row["document_id"], 0) + 1
    spans = []
    for row in chosen:
        impact = impacts.get(row["id"])
        spans.append((row["id"], row["document_chunk_id"], impact["conflicting_start"] if impact else row["evidence_start"], impact["conflicting_end"] if impact else row["evidence_end"]))
    authors = contributions.for_spans(conn, spans)

    nodes: dict[str, dict] = {}
    edges = []
    for row in chosen:
        req_id, doc_id = f"req:{row['lineage_id']}", f"doc:{row['document_id']}"
        req_level, doc_level = lineage_levels.get(row["lineage_id"]), document_levels.get(row["document_id"])
        state = f"affected_{doc_level}" if doc_level else "dependent_unaffected"
        nodes.setdefault(req_id, {"id": req_id, "kind": "requirement", "label": f"{row['public_ref']} · {row['subject'].replace('_', ' ')}", "requirement_text": row["requirement_text"], "regulation_title": row["regulation_title"], "state": f"affected_{req_level}" if req_level else "current", "impact_level": req_level})
        impact = impacts.get(row["id"])
        nodes.setdefault(doc_id, {"id": doc_id, "kind": "document", "label": row["name"], "doc_type": row["doc_type"], "owner": row["owner_name"], "owner_id": row["owner_id"], "state": state, "impact_level": doc_level, "dependency_count": dependency_counts[row["document_id"]], "change_source": impact["change_source"] if impact else None})
        target = doc_id
        if level == "section":
            target = f"sec:{row['document_chunk_id']}"
            nodes.setdefault(target, {"id": target, "kind": "section", "parent": doc_id, "label": row["section_path"] or row["name"], "page": row["page_number"], "state": state, "impact_level": doc_level})
        impact = impacts.get(row["id"])
        edges.append({"id": row["id"], "source": req_id, "target": target, "relationship_type": row["relationship_type"], "confidence": row["confidence"], "lineage_id": row["lineage_id"], "document_id": row["document_id"], "document_chunk_id": row["document_chunk_id"], "evidence_start": row["evidence_start"], "evidence_end": row["evidence_end"], "page_number": row["page_number"], "impact_level": impact["impact_level"] if impact else None, "severity": edge_levels.get(row["id"]), "change_source": impact["change_source"] if impact else None, "impact_reason": impact["reason"] if impact else None, "change_summary": impact["change_summary"] if impact else None, "affected_start": impact["conflicting_start"] if impact else None, "affected_end": impact["conflicting_end"] if impact else None, "contributor": authors.get(row["id"])})
    all_ids = {f"req:{r['lineage_id']}" for r in rows} | {f"doc:{r['document_id']}" for r in rows}
    if level == "section": all_ids |= {f"sec:{r['document_chunk_id']}" for r in rows}
    all_docs, shown_docs = {r["document_id"] for r in rows}, {r["document_id"] for r in chosen}
    return {"nodes": list(nodes.values()), "edges": edges, "hidden_document_count": len(all_docs - shown_docs), "truncated": {"nodes_omitted": len(all_ids - set(nodes)), "edges_omitted": len(rows) - len(edges)}}
