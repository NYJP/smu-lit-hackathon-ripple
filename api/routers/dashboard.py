"""Personalized work dashboard. Relevance ranks and explains; it never gates."""

from __future__ import annotations

from api.sqlite_driver import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.db import get_db
from api.services import relevance, severity as severity_service, workflow

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _next_action(status: str) -> str:
    return {
        "detected": "Start review", "awaiting_review": "Start review",
        "in_review": "Continue review", "needs_analysis": "Complete analysis",
        "patch_proposed": "Review wording", "awaiting_approval": "Approve wording",
    }.get(status, "View impact")


@router.get("")
def get_dashboard(
    scope: Literal["me", "all"] = "me",
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    document_ids = [row["id"] for row in conn.execute("SELECT id FROM documents ORDER BY created_at DESC")]
    signals = relevance.relevance_for(conn, user["id"], document_ids)
    open_clause, open_values = workflow.open_status_sql("i.review_status")
    rows = conn.execute(
        f"""SELECT i.*, d.name AS document_name, d.doc_type, d.owner_id, u.display_name AS owner_name,
                   c.summary AS change_summary, c.source, c.change_type, c.effective_date,
                   dc.section_path, dc.ordinal,
                   COUNT(*) OVER (PARTITION BY i.regulatory_change_id, i.document_id) AS affected_clause_count
              FROM impacts i
              JOIN documents d ON d.id=i.document_id
              JOIN users u ON u.id=d.owner_id
              JOIN regulatory_changes c ON c.id=i.regulatory_change_id
              JOIN document_chunks dc ON dc.id=i.document_chunk_id
             WHERE i.impact_level <> 'none' AND {open_clause}
             ORDER BY i.created_at DESC, i.rowid DESC""",
        open_values,
    ).fetchall()
    today = datetime.now(timezone.utc).date()
    feed = []
    severity_counts = severity_service.counts_template()
    for row in rows:
        signal = signals.get(row["document_id"], {"reason": "Monitored across your workspace.", "weight": 0})
        if scope == "me" and int(signal["weight"]) == 0:
            continue
        item = dict(row)
        item["severity"] = severity_service.derive_severity(row, row)
        item["review_status_label"] = workflow.STATUS_LABELS.get(row["review_status"], row["review_status"])
        item["relevance"] = signal
        item["next_action"] = _next_action(row["review_status"])
        item["clause_label"] = row["section_path"] or f"Clause {row['ordinal'] + 1}"
        severity_counts[item["severity"]] += 1
        due_score = 0
        if row["due_date"]:
            try:
                days = (datetime.fromisoformat(row["due_date"][:10]).date() - today).days
                due_score = 4 if days < 0 else 3 if days <= 7 else 2 if days <= 30 else 1
            except ValueError:
                pass
        item["_rank"] = severity_service.SEVERITY_RANK[item["severity"]] * 100 + int(signal["weight"]) * 10 + due_score
        feed.append(item)
    feed.sort(key=lambda item: (-item.pop("_rank"), item.get("due_date") or "9999"))
    feed = feed[:50]

    resolved_since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    resolved_rows = conn.execute(
        """SELECT i.id, i.document_id, i.resolved_at, d.name AS document_name, c.summary AS change_summary
             FROM impacts i JOIN documents d ON d.id=i.document_id
             JOIN regulatory_changes c ON c.id=i.regulatory_change_id
            WHERE i.review_status='resolved' AND i.resolved_at>=?
            ORDER BY i.resolved_at DESC, i.rowid DESC LIMIT 8""",
        (resolved_since,),
    ).fetchall()
    recently_resolved = [dict(row) for row in resolved_rows if scope == "all" or int(signals.get(row["document_id"], {"weight": 0})["weight"]) > 0]

    def count_status(*statuses: str) -> int:
        return sum(1 for item in feed if item["review_status"] in statuses)

    cards = {
        "action_required": sum(1 for item in feed if item["assigned_to"] == user["id"] or (item["owner_id"] == user["id"] and item["severity"] in ("critical", "high"))),
        "review_required": count_status("detected", "awaiting_review", "in_review", "needs_analysis"),
        "awaiting_approval": count_status("patch_proposed", "awaiting_approval"),
        "resolved_recently": len(recently_resolved),
        "documents_monitored": len(document_ids) if scope == "all" else sum(1 for signal in signals.values() if int(signal["weight"]) > 0),
    }

    graph_nodes: list[dict] = []
    graph_edges: list[dict] = []
    node_ids: set[str] = set()
    for item in feed:
        document_node = f"document:{item['document_id']}"
        change_node = f"change:{item['regulatory_change_id']}"
        for node_id, kind, label in ((document_node, "document", item["document_name"]), (change_node, "change", item["change_summary"])):
            if node_id not in node_ids and len(graph_nodes) < 40:
                graph_nodes.append({"id": node_id, "kind": kind, "label": label, "severity": item["severity"]})
                node_ids.add(node_id)
        if document_node in node_ids and change_node in node_ids:
            graph_edges.append({"source": change_node, "target": document_node, "confidence": item["confidence"]})

    activity = conn.execute(
        "SELECT id,title,body,subject_type,subject_id,read_at,created_at FROM notifications WHERE user_id=? ORDER BY rowid DESC LIMIT 6",
        (user["id"],),
    ).fetchall()
    last_scan = conn.execute("SELECT MAX(created_at) AS at FROM scans").fetchone()["at"]
    return {
        "scope": scope, "cards": cards, "feed": feed,
        "graph_preview": {"nodes": graph_nodes, "edges": graph_edges},
        "severity_counts": severity_counts, "recently_resolved": recently_resolved,
        "activity": [dict(row) for row in activity], "last_scan_at": last_scan,
    }
