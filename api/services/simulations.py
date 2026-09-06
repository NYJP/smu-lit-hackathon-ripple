"""Simulation preparation, cache estimation, and background execution.

Hypothetical requirements exist only as ``regulatory_changes.proposed_snapshot``.
This module never writes ``regulatory_requirements`` or document source content.
"""
from __future__ import annotations

import json
import os
from api.sqlite_driver import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from api.services import changes as change_utils
from api.services import impact, jobs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def proposal(previous: sqlite3.Row | None, edit: sqlite3.Row) -> dict[str, Any]:
    proposed = dict(previous) if previous else {"subject": "new requirement", "value": None}
    for key in (
        "requirement_text", "value", "value_numeric", "value_unit", "comparator",
        "condition", "exception", "effective_date",
    ):
        value = edit[f"proposed_{key}"]
        if value is not None:
            proposed[key] = value
    return proposed


def current_requirement(conn: sqlite3.Connection, lineage_id: str | None) -> sqlite3.Row | None:
    if not lineage_id:
        return None
    return conn.execute(
        """SELECT q.* FROM requirement_lineages l
           JOIN regulatory_requirements q ON q.id=l.current_version_id WHERE l.id=?""",
        (lineage_id,),
    ).fetchone()


def estimate(conn: sqlite3.Connection, simulation_id: str) -> dict[str, Any]:
    dependency_count = 0
    cached_count = 0
    model = os.environ.get("RIPPLE_REASONING_MODEL", "gpt-5")
    edits = conn.execute(
        "SELECT * FROM simulation_edits WHERE simulation_id=? ORDER BY created_at, id",
        (simulation_id,),
    ).fetchall()
    for edit in edits:
        if not edit["lineage_id"]:
            continue
        previous = current_requirement(conn, edit["lineage_id"])
        proposed = proposal(previous, edit)
        change_type, old_value, new_value, _ = impact.change_fields(previous, proposed, edit["op"])
        if change_type == "editorial":
            continue
        rows = conn.execute(
            """SELECT dep.id AS dependency_id, dep.document_id, dep.document_chunk_id,
                      c.content, c.ordinal, c.section_path, c.page_number
               FROM dependencies dep JOIN document_chunks c ON c.id=dep.document_chunk_id
               WHERE dep.lineage_id=? AND dep.status='active'""",
            (edit["lineage_id"],),
        ).fetchall()
        dependency_count += len(rows)
        for row in rows:
            previous_hash = change_utils.requirement_content_hash(dict(previous) if previous else None)
            new_hash = change_utils.requirement_content_hash(proposed)
            chunk_hash = change_utils.document_chunk_hash(row)
            span, _, _ = impact.locate_literal(row["content"], old_value) if impact.normalized_literal(old_value) != impact.normalized_literal(new_value) else (None, None, None)
            selected_model = "literal_override-v1" if span is not None else model
            cached = conn.execute(
                """SELECT 1 FROM impact_cache WHERE dependency_id=?
                   AND previous_requirement_hash=? AND new_requirement_hash=?
                   AND document_chunk_hash=? AND model=?""",
                (row["dependency_id"], previous_hash, new_hash, chunk_hash, selected_model),
            ).fetchone()
            cached_count += int(cached is not None)
    uncached_count = dependency_count - cached_count
    return {
        "dependency_count": dependency_count,
        "cached_count": cached_count,
        "estimated_cost_usd": round(uncached_count * 0.0002, 4),
    }


def run_simulation_job(conn: sqlite3.Connection, job_id: str) -> None:
    job = jobs.get_job(conn, job_id)
    if job is None:
        return
    simulation_id = job["subject_id"]
    try:
        jobs.update_job(conn, job_id, status="running", progress=0.05, step="preparing_simulation")
        simulation = conn.execute("SELECT 1 FROM simulations WHERE id=?", (simulation_id,)).fetchone()
        if simulation is None:
            jobs.update_job(conn, job_id, status="failed", progress=1, step="failed", error_message="Simulation not found.")
            return
        conn.execute("UPDATE simulations SET status='running', updated_at=? WHERE id=?", (_now(), simulation_id))
        conn.execute("DELETE FROM regulatory_changes WHERE simulation_id=?", (simulation_id,))
        edits = conn.execute(
            "SELECT * FROM simulation_edits WHERE simulation_id=? ORDER BY created_at, id",
            (simulation_id,),
        ).fetchall()
        conn.commit()
        created_changes: list[str] = []
        impact_count = cache_hits = 0
        total = max(1, len(edits))
        for index, edit in enumerate(edits):
            jobs.update_job(
                conn, job_id, progress=0.15 + 0.7 * index / total,
                step="evaluating_dependencies",
                stage_counters={"edits_total": len(edits), "edits_complete": index},
            )
            previous = current_requirement(conn, edit["lineage_id"])
            proposed = proposal(previous, edit)
            change_type, old_value, new_value, summary = impact.change_fields(previous, proposed, edit["op"])
            if change_type == "editorial":
                continue
            change_id = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO regulatory_changes
                   (id,lineage_id,source,simulation_id,previous_requirement_id,proposed_snapshot,
                    change_type,old_value,new_value,summary,source_section,effective_date,
                    analysis_status,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'analysing',?)""",
                (change_id, edit["lineage_id"], "simulation", simulation_id,
                 previous["id"] if previous else None, json.dumps(proposed), change_type,
                 old_value, new_value, summary, proposed.get("source_section"),
                 proposed.get("effective_date"), _now()),
            )
            conn.commit()
            result = impact.analyse_change(conn, change_id) if previous else impact.ImpactAnalysisResult()
            jobs.add_usage(conn, job_id, result.usage)
            conn.execute("UPDATE regulatory_changes SET analysis_status='complete' WHERE id=?", (change_id,))
            conn.commit()
            created_changes.append(change_id)
            impact_count += result.impacts_created
            cache_hits += result.cache_hits
        jobs.update_job(conn, job_id, progress=0.92, step="summarizing_results")
        affected_documents = conn.execute(
            """SELECT COUNT(DISTINCT i.document_id) AS n FROM impacts i
               JOIN regulatory_changes c ON c.id=i.regulatory_change_id
               WHERE c.simulation_id=? AND i.impact_level!='none'""",
            (simulation_id,),
        ).fetchone()["n"]
        examined_documents = conn.execute(
            """SELECT COUNT(DISTINCT d.document_id) AS n FROM dependencies d
               JOIN simulation_edits e ON e.lineage_id=d.lineage_id
               WHERE e.simulation_id=? AND d.status='active'""",
            (simulation_id,),
        ).fetchone()["n"]
        conn.execute("UPDATE simulations SET status='complete', updated_at=? WHERE id=?", (_now(), simulation_id))
        conn.commit()
        jobs.update_job(
            conn, job_id, status="succeeded", progress=1, step="completed",
            stage_counters={"edits_total": len(edits), "edits_complete": len(edits)},
            result={
                "simulation_id": simulation_id, "change_ids": created_changes,
                "documents_examined": examined_documents, "affected_documents": affected_documents,
                "impacts_created": impact_count, "cache_hits": cache_hits,
            },
        )
    except Exception as exc:
        conn.rollback()
        conn.execute("UPDATE simulations SET status='failed', updated_at=? WHERE id=?", (_now(), simulation_id))
        conn.commit()
        jobs.update_job(conn, job_id, status="failed", progress=1, step="failed", error_message=str(exc))
