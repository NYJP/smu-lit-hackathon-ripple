"""Candidate retrieval and durable dependency mapping (PRD section 7.6)."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import sqlite_vec

from api.services import openai, retrieval

_RRF_OFFSET = 60
_MIN_SIMILARITY = 0.45
_DEPENDENCY_THRESHOLD = 0.60
_BATCH_SIZE = 8
_RELATIONSHIPS = {"restates", "implements", "references", "defines"}

_SYSTEM = (
    "Decide whether each candidate passage depends on the regulatory requirement. "
    "A passage depends on a requirement when changing the requirement would oblige a lawyer to review that passage. "
    "Use restates when it reproduces the rule or value, implements when it operationalises the rule without quoting it, "
    "references when it defers generically to the rule, and defines when it defines a term the rule turns on. "
    "Vocabulary overlap alone is not a dependency. When a dependency exists, copy the exact passage substring carrying it."
)

_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["decisions"],
    "properties": {"decisions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["chunk_id", "depends", "relationship_type", "confidence", "rationale", "evidence_span"],
        "properties": {
            "chunk_id": {"type": "string"}, "depends": {"type": "boolean"},
            "relationship_type": {"type": ["string", "null"], "enum": ["restates", "implements", "references", "defines", None]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"}, "evidence_span": {"type": ["string", "null"]},
        },
    }}},
}


@dataclass(frozen=True)
class MappingResult:
    dependencies_added: int = 0
    candidates_seen: int = 0
    usage: openai.Usage = openai.Usage()

    def add(self, other: "MappingResult") -> "MappingResult":
        return MappingResult(
            self.dependencies_added + other.dependencies_added,
            self.candidates_seen + other.candidates_seen,
            self.usage.add(other.usage),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rrf(*legs: Iterable[str]) -> list[str]:
    scores: dict[str, float] = {}
    for leg in legs:
        for rank, identifier in enumerate(leg, start=1):
            scores[identifier] = scores.get(identifier, 0) + 1 / (_RRF_OFFSET + rank)
    return [identifier for identifier, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)]


def _vector_ids(conn: sqlite3.Connection, table: str, id_column: str, vector: bytes, limit: int) -> list[str]:
    try:
        rows = conn.execute(f"SELECT {id_column}, distance FROM {table} WHERE embedding MATCH ? AND k = ?", (vector, limit)).fetchall()
    except sqlite3.Error:
        return []
    return [row[id_column] for row in rows if 1 - float(row["distance"]) >= _MIN_SIMILARITY]


def _high_signal_query(row: sqlite3.Row, text_field: str) -> str:
    tokens: list[str] = []
    value = row["value"] if "value" in row.keys() else None
    if value:
        tokens.extend(re.findall(r"[\w]+", str(value)))
        tokens.append(re.sub(r"\s+", "", str(value)))
    tokens.extend(re.findall(r"[\w]+", str(row[text_field]))[:12])
    return " OR ".join(f'"{token}"' for token in dict.fromkeys(tokens) if token)


def _rows_by_ids(conn: sqlite3.Connection, query: str, ids: list[str]) -> dict[str, sqlite3.Row]:
    if not ids:
        return {}
    rows = conn.execute(query.format(placeholders=",".join("?" * len(ids))), ids).fetchall()
    return {row["id"]: row for row in rows}


def _candidate_requirements(conn: sqlite3.Connection, chunk: sqlite3.Row) -> list[sqlite3.Row]:
    vector = conn.execute("SELECT embedding FROM vec_chunks WHERE chunk_id = ?", (chunk["id"],)).fetchone()
    vector_leg = _vector_ids(conn, "vec_requirements", "requirement_id", vector["embedding"], 15) if vector else []
    query = retrieval._fts_query(chunk["content"])
    lexical = conn.execute("SELECT requirement_id FROM fts_requirements WHERE fts_requirements MATCH ? ORDER BY bm25(fts_requirements) LIMIT 15", (query,)).fetchall() if query else []
    ids = _rrf(vector_leg, [row["requirement_id"] for row in lexical])[:20]
    rows = _rows_by_ids(conn, "SELECT q.*, l.public_ref FROM regulatory_requirements q JOIN requirement_lineages l ON l.id = q.lineage_id WHERE q.is_current = 1 AND q.id IN ({placeholders})", ids)
    return [rows[identifier] for identifier in ids if identifier in rows]


def _candidate_chunks(conn: sqlite3.Connection, requirement: sqlite3.Row, document_ids: set[str] | None = None) -> list[sqlite3.Row]:
    vector = conn.execute("SELECT embedding FROM vec_requirements WHERE requirement_id = ?", (requirement["id"],)).fetchone()
    vector_leg = _vector_ids(conn, "vec_chunks", "chunk_id", vector["embedding"], 40) if vector else []
    query = _high_signal_query(requirement, "requirement_text")
    lexical = conn.execute("SELECT chunk_id FROM fts_chunks WHERE fts_chunks MATCH ? ORDER BY bm25(fts_chunks) LIMIT 40", (query,)).fetchall() if query else []
    ids = _rrf(vector_leg, [row["chunk_id"] for row in lexical])[:60]
    rows = _rows_by_ids(conn, "SELECT c.* FROM document_chunks c WHERE c.id IN ({placeholders})", ids)
    return [rows[identifier] for identifier in ids if identifier in rows and (document_ids is None or rows[identifier]["document_id"] in document_ids)]


def _locate_span(content: str, evidence_span: str | None) -> tuple[str | None, int | None, int | None]:
    if not evidence_span:
        return None, None, None
    start = content.find(evidence_span)
    if start < 0:
        start = content.casefold().find(evidence_span.casefold())
    if start < 0:
        compact: list[str] = []
        positions: list[int] = []
        for index, char in enumerate(content):
            if char.isspace():
                if compact and compact[-1] != " ":
                    compact.append(" ")
                    positions.append(index)
            else:
                compact.append(char.casefold())
                positions.append(index)
        target = " ".join(evidence_span.casefold().split())
        normalised = "".join(compact)
        found = normalised.find(target)
        if found < 0:
            return evidence_span, None, None
        start = positions[found]
        end = positions[found + len(target) - 1] + 1
        return content[start:end], start, end
    end = start + len(evidence_span)
    return content[start:end], start, end


def _adjudicate(requirement: sqlite3.Row, candidates: list[sqlite3.Row]) -> tuple[list[dict[str, Any]], openai.Usage]:
    if not candidates:
        return [], openai.Usage()
    supplied = "\n\n".join(
        f"Chunk {chunk['id']} | section {chunk['section_path'] or 'unknown'}\n{chunk['content']}" for chunk in candidates
    )
    fields = "\n".join(f"{key}: {requirement[key]}" for key in ("requirement_text", "subject", "value", "value_numeric", "value_unit", "comparator", "condition", "exception"))
    payload, usage = openai.structured_completion(
        _SYSTEM, f"Regulatory requirement:\n{fields}\n\nCandidate passages:\n{supplied}", _DECISION_SCHEMA,
        model=os.environ.get("RIPPLE_BULK_MODEL", "gpt-5-mini"), schema_name="dependency_decisions",
    )
    permitted = {chunk["id"] for chunk in candidates}
    decisions = [item for item in payload.get("decisions", []) if item.get("chunk_id") in permitted]
    return decisions, usage


def _write_dependency(conn: sqlite3.Connection, lineage_id: str, chunk: sqlite3.Row, decision: dict[str, Any], scan_id: str | None) -> int:
    if not decision.get("depends") or float(decision.get("confidence") or 0) < _DEPENDENCY_THRESHOLD:
        return 0
    relationship = decision.get("relationship_type")
    if relationship not in _RELATIONSHIPS:
        return 0
    evidence_span, evidence_start, evidence_end = _locate_span(chunk["content"], decision.get("evidence_span"))
    existing = conn.execute("SELECT id, status FROM dependencies WHERE lineage_id = ? AND document_chunk_id = ?", (lineage_id, chunk["id"])).fetchone()
    if existing is None:
        conn.execute(
            """INSERT INTO dependencies (id, lineage_id, document_chunk_id, document_id, relationship_type, confidence, rationale, evidence_span, evidence_start, evidence_end, found_by_scan_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, lineage_id, chunk["id"], chunk["document_id"], relationship, float(decision["confidence"]), str(decision.get("rationale") or ""), evidence_span, evidence_start, evidence_end, scan_id, _now()),
        )
        return 1
    if existing["status"] == "active":
        conn.execute(
            """UPDATE dependencies SET relationship_type = ?, confidence = ?, rationale = ?, evidence_span = ?, evidence_start = ?, evidence_end = ?, found_by_scan_id = ? WHERE id = ?""",
            (relationship, float(decision["confidence"]), str(decision.get("rationale") or ""), evidence_span, evidence_start, evidence_end, scan_id, existing["id"]),
        )
    return 0


def _write_pass(conn: sqlite3.Connection, document_id: str, lineage_id: str, direction: str, found: bool, candidates_seen: int, scan_id: str | None) -> None:
    conn.execute(
        """INSERT INTO mapping_passes (document_id, lineage_id, direction, dependency_found, candidates_seen, scan_id, mapped_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(document_id, lineage_id) DO UPDATE SET direction = excluded.direction, dependency_found = excluded.dependency_found,
             candidates_seen = excluded.candidates_seen, scan_id = excluded.scan_id, mapped_at = excluded.mapped_at""",
        (document_id, lineage_id, direction, int(found), candidates_seen, scan_id, _now()),
    )


def map_document(conn: sqlite3.Connection, document_id: str, scan_id: str | None = None) -> MappingResult:
    """Map one newly ingested document without revisiting other documents."""
    chunks = conn.execute("SELECT * FROM document_chunks WHERE document_id = ? ORDER BY ordinal", (document_id,)).fetchall()
    lineages = conn.execute("SELECT l.id, q.* FROM requirement_lineages l JOIN regulatory_requirements q ON q.id = l.current_version_id WHERE q.is_current = 1").fetchall()
    candidates_seen = {row["id"]: 0 for row in lineages}
    found = {row["id"]: False for row in lineages}
    added = 0
    usage = openai.Usage()
    for chunk in chunks:
        candidates = _candidate_requirements(conn, chunk)
        for requirement in candidates:
            candidates_seen[requirement["lineage_id"]] += 1
        for start in range(0, len(candidates), _BATCH_SIZE):
            batch = candidates[start:start + _BATCH_SIZE]
            # One chunk is adjudicated against each candidate requirement; this keeps the structured output
            # keyed to the stable chunk id while retaining a compact batch at the external boundary.
            for requirement in batch:
                decisions, call_usage = _adjudicate(requirement, [chunk])
                usage = usage.add(call_usage)
                for decision in decisions:
                    if decision.get("depends") and float(decision.get("confidence") or 0) >= _DEPENDENCY_THRESHOLD:
                        found[requirement["lineage_id"]] = True
                    added += _write_dependency(conn, requirement["lineage_id"], chunk, decision, scan_id)
    for lineage in lineages:
        _write_pass(conn, document_id, lineage["id"], "document_first", found[lineage["id"]], candidates_seen[lineage["id"]], scan_id)
    conn.commit()
    return MappingResult(added, sum(candidates_seen.values()), usage)


def map_lineage(conn: sqlite3.Connection, lineage_id: str, document_ids: set[str] | None = None, scan_id: str | None = None) -> MappingResult:
    """Map a newly created lineage across the supplied document scope."""
    requirement = conn.execute("SELECT q.*, l.public_ref FROM regulatory_requirements q JOIN requirement_lineages l ON l.id = q.lineage_id WHERE q.lineage_id = ? AND q.is_current = 1", (lineage_id,)).fetchone()
    if requirement is None:
        return MappingResult()
    if document_ids is None:
        document_ids = {row["id"] for row in conn.execute("SELECT id FROM documents WHERE status = 'ready'").fetchall()}
    chunks = _candidate_chunks(conn, requirement, document_ids)
    candidates_seen = {document_id: 0 for document_id in document_ids}
    found = {document_id: False for document_id in document_ids}
    added = 0
    usage = openai.Usage()
    for start in range(0, len(chunks), _BATCH_SIZE):
        batch = chunks[start:start + _BATCH_SIZE]
        decisions, call_usage = _adjudicate(requirement, batch)
        usage = usage.add(call_usage)
        by_id = {chunk["id"]: chunk for chunk in batch}
        for chunk in batch:
            candidates_seen[chunk["document_id"]] += 1
        for decision in decisions:
            chunk = by_id[decision["chunk_id"]]
            if decision.get("depends") and float(decision.get("confidence") or 0) >= _DEPENDENCY_THRESHOLD:
                found[chunk["document_id"]] = True
            added += _write_dependency(conn, lineage_id, chunk, decision, scan_id)
    for document_id in document_ids:
        _write_pass(conn, document_id, lineage_id, "requirement_first", found[document_id], candidates_seen[document_id], scan_id)
    conn.commit()
    return MappingResult(added, sum(candidates_seen.values()), usage)
