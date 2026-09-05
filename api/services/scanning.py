"""Background reconciliation for mapping and impact gaps."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from api.services import impact, jobs, mapping

_SCAN_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scope_predicate(scope: str, scope_id: str | None) -> tuple[str, list[Any]]:
    if scope == "document" and scope_id:
        return " AND d.id = ?", [scope_id]
    if scope == "lineage" and scope_id:
        return " AND l.id = ?", [scope_id]
    return "", []


def detect_gaps(
    conn: sqlite3.Connection,
    scope: str = "stale",
    scope_id: str | None = None,
) -> dict[str, list[Any]]:
    """Return the exact G1–G4 work set without external calls."""
    suffix, values = _scope_predicate(scope, scope_id)
    g1 = conn.execute(
        """SELECT d.id AS document_id, l.id AS lineage_id
           FROM documents d CROSS JOIN requirement_lineages l
           LEFT JOIN mapping_passes p ON p.document_id=d.id AND p.lineage_id=l.id
           WHERE d.status='ready' AND p.document_id IS NULL""" + suffix,
        values,
    ).fetchall()
    g2 = conn.execute(
        """SELECT c.id AS change_id, dep.id AS dependency_id, dep.document_id
           FROM dependencies dep
           JOIN documents d ON d.id=dep.document_id
           JOIN regulatory_changes c ON c.lineage_id=dep.lineage_id
           JOIN requirement_lineages l ON l.id=dep.lineage_id
           LEFT JOIN impacts i ON i.dependency_id=dep.id AND i.regulatory_change_id=c.id
           WHERE dep.status='active' AND c.simulation_id IS NULL AND i.id IS NULL""" + suffix,
        values,
    ).fetchall()
    g3 = conn.execute(
        """SELECT dep.id AS dependency_id, dep.document_id, dep.lineage_id
           FROM dependencies dep
           JOIN documents d ON d.id=dep.document_id
           JOIN requirement_lineages l ON l.id=dep.lineage_id
           LEFT JOIN document_chunks chunk ON chunk.id=dep.document_chunk_id
           WHERE dep.status='active' AND (
             chunk.id IS NULL OR
             (dep.evidence_span IS NOT NULL AND instr(chunk.content, dep.evidence_span)=0)
           )""" + suffix,
        values,
    ).fetchall()
    pass_rows = conn.execute(
        """SELECT p.document_id, p.lineage_id, p.basis_hash
           FROM mapping_passes p
           JOIN documents d ON d.id=p.document_id
           JOIN requirement_lineages l ON l.id=p.lineage_id
           WHERE d.status='ready'""" + suffix,
        values,
    ).fetchall()
    g4 = []
    for row in pass_rows:
        current_hash = mapping.mapping_basis_hash(conn, row["document_id"], row["lineage_id"])
        if not row["basis_hash"] or row["basis_hash"] != current_hash:
            g4.append(dict(row))
    return {
        "unmapped_pairs": [dict(row) for row in g1],
        "unevaluated_impacts": [dict(row) for row in g2],
        "orphaned_dependencies": [dict(row) for row in g3],
        "restaled_mappings": g4,
    }


def gap_summary(conn: sqlite3.Connection, scope: str = "stale", scope_id: str | None = None) -> dict[str, Any]:
    gaps = detect_gaps(conn, scope, scope_id)
    counts = {name: len(items) for name, items in gaps.items()}
    active = conn.execute(
        """SELECT s.id, s.job_id, s.status FROM scans s
           WHERE s.status IN ('queued','running') ORDER BY s.created_at LIMIT 1"""
    ).fetchone()
    estimated_calls = (counts["unmapped_pairs"] + counts["restaled_mappings"] + 7) // 8
    estimated_calls += (counts["unevaluated_impacts"] + 5) // 6
    return {
        "is_stale": any(counts.values()),
        "gaps": counts,
        "estimated_cost_usd": round(estimated_calls * 0.002, 4),
        "running_scan_id": active["id"] if active else None,
        "running_job_id": active["job_id"] if active else None,
    }


def start_scan(
    conn: sqlite3.Connection,
    *,
    trigger: str,
    scope: str = "stale",
    scope_id: str | None = None,
    initiated_by: str | None = None,
) -> tuple[str, str, bool]:
    """Create or reuse equivalent queued/running scan work."""
    active = conn.execute(
        """SELECT id, job_id FROM scans
           WHERE status IN ('queued','running') AND trigger=? AND scope=?
             AND COALESCE(scope_id,'')=COALESCE(?,'')
           ORDER BY created_at LIMIT 1""",
        (trigger, scope, scope_id),
    ).fetchone()
    if active:
        return active["id"], active["job_id"], False
    scan_id = uuid.uuid4().hex
    now = _now()
    conn.execute(
        """INSERT INTO scans
           (id, trigger, scope, scope_id, initiated_by, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
        (scan_id, trigger, scope, scope_id, initiated_by, now),
    )
    job_id = jobs.create_job(
        conn,
        "scan",
        "scan",
        scan_id,
        initiated_by=initiated_by,
        input_payload={"trigger": trigger, "scope": scope, "scope_id": scope_id},
    )
    conn.execute("UPDATE scans SET job_id=? WHERE id=?", (job_id, scan_id))
    conn.commit()
    return scan_id, job_id, True


def _scan_update(conn: sqlite3.Connection, scan_id: str, **values: Any) -> None:
    if not values:
        return
    assignments = ", ".join(f"{key}=?" for key in values)
    conn.execute(f"UPDATE scans SET {assignments} WHERE id=?", [*values.values(), scan_id])
    conn.commit()


def run_scan_job(conn: sqlite3.Connection, job_id: str) -> None:
    job = jobs.get_job(conn, job_id)
    if job is None:
        return
    scan_id = job["subject_id"]
    scan = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    if scan is None:
        jobs.update_job(conn, job_id, status="failed", step="failed", error_message="Scan not found.")
        return
    with _SCAN_LOCK:
        try:
            jobs.update_job(conn, job_id, status="running", progress=0.05, step="detecting_gaps")
            _scan_update(conn, scan_id, status="running", started_at=_now(), error_message=None)
            gaps = detect_gaps(conn, scan["scope"], scan["scope_id"])
            initial_counts = {name: len(items) for name, items in gaps.items()}
            jobs.update_job(conn, job_id, progress=0.15, step="mapping", stage_counters=initial_counts)

            for item in gaps["orphaned_dependencies"]:
                dependency = conn.execute("SELECT * FROM dependencies WHERE id=?", (item["dependency_id"],)).fetchone()
                if dependency is None:
                    continue
                conn.execute(
                    "UPDATE dependencies SET status='dismissed', rationale='Source text changed' WHERE id=?",
                    (dependency["id"],),
                )
                conn.execute(
                    """INSERT INTO dependency_events
                       (id, dependency_id, event_type, previous_status, new_status,
                        previous_relationship_type, new_relationship_type,
                        previous_evidence_span, new_evidence_span, scan_id, created_at)
                       VALUES (?, ?, 'dismissed', 'active', 'dismissed', ?, ?, ?, ?, ?, ?)""",
                    (uuid.uuid4().hex, dependency["id"], dependency["relationship_type"],
                     dependency["relationship_type"], dependency["evidence_span"],
                     dependency["evidence_span"], scan_id, _now()),
                )
            conn.commit()
            _scan_update(conn, scan_id, dependencies_removed=len(gaps["orphaned_dependencies"]))

            if scan["scope"] == "full":
                document_ids = {
                    row["id"] for row in conn.execute(
                        "SELECT id FROM documents WHERE status='ready'"
                    ).fetchall()
                }
            else:
                document_ids = {
                    item["document_id"]
                    for name in ("unmapped_pairs", "restaled_mappings", "orphaned_dependencies")
                    for item in gaps[name]
                }
            dependencies_added = 0
            mapping_pairs_checked = 0
            requirements_scanned = 0
            lineage_count = conn.execute(
                "SELECT COUNT(*) AS n FROM requirement_lineages"
            ).fetchone()["n"]
            for index, document_id in enumerate(sorted(document_ids), start=1):
                result = mapping.map_document(conn, document_id, scan_id=scan_id, job_id=job_id)
                dependencies_added += result.dependencies_added
                mapping_pairs_checked += lineage_count
                requirements_scanned += lineage_count
                _scan_update(
                    conn, scan_id, documents_scanned=index,
                    requirements_scanned=requirements_scanned,
                    mapping_pairs_checked=mapping_pairs_checked,
                    dependencies_added=dependencies_added,
                )
                jobs.update_job(
                    conn, job_id,
                    progress=0.15 + 0.45 * index / max(1, len(document_ids)),
                    step="mapping",
                    stage_counters={**initial_counts, "documents_completed": index, "documents_total": len(document_ids)},
                )

            jobs.update_job(conn, job_id, progress=0.65, step="evaluating_impacts")
            refreshed = detect_gaps(conn, scan["scope"], scan["scope_id"])
            dependencies_by_change: dict[str, set[str]] = defaultdict(set)
            for item in refreshed["unevaluated_impacts"]:
                dependencies_by_change[item["change_id"]].add(item["dependency_id"])
            impacts_created = 0
            new_high_impacts = 0
            cache_hits = 0
            for index, (change_id, dependency_ids) in enumerate(dependencies_by_change.items(), start=1):
                result = impact.analyse_change(
                    conn, change_id, dependency_ids=dependency_ids, scan_id=scan_id
                )
                jobs.add_usage(conn, job_id, result.usage)
                impacts_created += result.impacts_created
                new_high_impacts += result.counts["high"]
                cache_hits += result.cache_hits
                _scan_update(
                    conn, scan_id, impacts_created=impacts_created,
                    new_high_impacts=new_high_impacts, cache_hits=cache_hits,
                )
                jobs.update_job(
                    conn, job_id,
                    progress=0.65 + 0.25 * index / max(1, len(dependencies_by_change)),
                    step="evaluating_impacts",
                )

            jobs.update_job(conn, job_id, progress=0.95, step="finalizing")
            usage_row = jobs.get_job(conn, job_id)
            _scan_update(
                conn, scan_id, status="succeeded", finished_at=_now(),
                prompt_tokens=usage_row["prompt_tokens"],
                completion_tokens=usage_row["completion_tokens"],
                estimated_cost_usd=usage_row["estimated_cost_usd"] or 0,
            )
            jobs.update_job(
                conn, job_id, status="succeeded", progress=1, step="completed",
                result={
                    "scan_id": scan_id,
                    "gaps": initial_counts,
                    "documents_scanned": len(document_ids),
                    "dependencies_added": dependencies_added,
                    "impacts_created": impacts_created,
                    "cache_hits": cache_hits,
                },
            )
        except Exception as exc:
            conn.rollback()
            _scan_update(conn, scan_id, status="failed", error_message=str(exc), finished_at=_now())
            jobs.update_job(
                conn, job_id, status="failed", progress=1, step="failed",
                error_message=str(exc),
            )


def run_change_analysis_job(conn: sqlite3.Connection, job_id: str) -> None:
    job = jobs.get_job(conn, job_id)
    if job is None:
        return
    change_id = job["subject_id"]
    try:
        jobs.update_job(conn, job_id, status="running", progress=0.1, step="evaluating_impacts")
        conn.execute("UPDATE regulatory_changes SET analysis_status='analysing' WHERE id=?", (change_id,))
        conn.commit()
        result = impact.analyse_change(conn, change_id)
        jobs.add_usage(conn, job_id, result.usage)
        conn.execute("UPDATE regulatory_changes SET analysis_status='complete' WHERE id=?", (change_id,))
        conn.commit()
        result_payload: dict[str, Any] = {"change_id": change_id, **result.as_dict()}
        input_payload = json.loads(job["input_json"]) if job["input_json"] else {}
        if input_payload.get("trigger_scan"):
            scan_id, scan_job_id, scan_created = start_scan(
                conn, trigger="policy_change", scope="stale"
            )
            result_payload.update({"scan_id": scan_id, "scan_job_id": scan_job_id})
        else:
            scan_created = False
            scan_job_id = None
        jobs.update_job(
            conn, job_id, status="succeeded", progress=1, step="completed",
            result=result_payload,
        )
        if scan_created and scan_job_id:
            run_scan_job(conn, scan_job_id)
    except Exception as exc:
        conn.rollback()
        conn.execute("UPDATE regulatory_changes SET analysis_status='failed' WHERE id=?", (change_id,))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="failed", error_message=str(exc))
