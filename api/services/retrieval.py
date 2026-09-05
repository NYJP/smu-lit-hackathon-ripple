"""Requirement extraction, embedding persistence, and hybrid retrieval."""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import sqlite_vec

from api.services import openai, parsing

_WINDOW_CHARS = 48_000
_OVERLAP_CHARS = 3_200
_RRF_OFFSET = 60
_SEARCH_LIMIT = 40
_RESULT_LIMIT = 20
_UNITS = {"g", "kg", "mg", "days", "months", "years", "sgd", "usd", "percent", "count", "other"}
_UNIT_ALIASES = {"gram": "g", "grams": "g", "gramme": "g", "grammes": "g", "%": "percent", "percentage": "percent", "percentages": "percent", "dollar": "usd", "dollars": "usd"}
_TYPES = {"threshold", "duration", "prohibition", "obligation", "definition", "notification", "exception", "procedure", "other"}
_COMPARATORS = {"gt", "gte", "lt", "lte", "eq", "between"}

_EXTRACTION_SYSTEM = (
    "You extract atomic legal requirements from regulatory text. An atomic requirement states exactly one obligation about exactly one subject and can be cited on its own. "
    "Split compound sentences into separate requirements. Never infer a requirement the text does not state. Quote the source sentence verbatim in verbatim_text. "
    "If a numeric limit is present, normalise it into value_numeric and value_unit and set the comparator. Return only text that creates, modifies, or defines a legal obligation — skip recitals, preambles, and commencement boilerplate, except where they set an effective date. "
    "Where the reference list of existing subjects contains a subject covering the same ground, reuse that exact subject string."
)

_REQUIREMENT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["requirements"],
    "properties": {
        "requirements": {
            "type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["requirement_text", "verbatim_text", "requirement_type", "subject", "value", "value_numeric", "value_unit", "comparator", "condition", "exception", "source_section", "source_page", "effective_date", "repeals_sections"],
                "properties": {
                    "requirement_text": {"type": "string"}, "verbatim_text": {"type": "string"},
                    "requirement_type": {"type": "string", "enum": sorted(_TYPES)}, "subject": {"type": "string"},
                    "value": {"type": ["string", "null"]}, "value_numeric": {"type": ["number", "null"]},
                    "value_unit": {"type": ["string", "null"], "enum": [*sorted(_UNITS), None]},
                    "comparator": {"type": ["string", "null"], "enum": [*sorted(_COMPARATORS), None]},
                    "condition": {"type": ["string", "null"]}, "exception": {"type": ["string", "null"]},
                    "source_section": {"type": ["string", "null"]}, "source_page": {"type": ["integer", "null"]},
                    "effective_date": {"type": ["string", "null"]}, "repeals_sections": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class ExtractedRequirement:
    data: dict[str, Any]
    embedding: list[float]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snake_case(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def _canonical_requirement(raw: dict[str, Any], page_count: int) -> dict[str, Any]:
    subject = _snake_case(str(raw.get("subject") or ""))
    text = str(raw.get("requirement_text") or "").strip()
    if not subject or not text:
        raise openai.ExternalServiceError("The configured model service returned an invalid requirement.")
    unit = raw.get("value_unit")
    if unit is not None:
        unit = _UNIT_ALIASES.get(str(unit).strip().lower(), str(unit).strip().lower())
        if unit not in _UNITS:
            unit = "other"
    requirement_type = raw.get("requirement_type")
    comparator = raw.get("comparator")
    if requirement_type not in _TYPES or comparator not in _COMPARATORS | {None}:
        raise openai.ExternalServiceError("The configured model service returned an invalid requirement.")
    page = raw.get("source_page")
    if page is not None and (not isinstance(page, int) or page < 1 or page > page_count):
        raise openai.ExternalServiceError("The configured model service returned an invalid requirement source page.")
    return {
        "requirement_text": text, "verbatim_text": str(raw.get("verbatim_text") or "").strip() or None,
        "requirement_type": requirement_type, "subject": subject, "value": raw.get("value"),
        "value_numeric": raw.get("value_numeric"), "value_unit": unit, "comparator": comparator,
        "condition": raw.get("condition"), "exception": raw.get("exception"),
        "source_section": raw.get("source_section"), "source_page": page,
        "effective_date": raw.get("effective_date"), "repeals_sections": list(raw.get("repeals_sections") or []),
    }


def _windows(parsed: parsing.RegulationParseResult) -> Iterable[str]:
    source = "\n\n".join(f"[Page {page.page_number}; section {page.current_section or 'unknown'}]\n{page.text}" for page in parsed.pages)
    if len(source) <= _WINDOW_CHARS:
        yield source
        return
    start = 0
    while start < len(source):
        yield source[start:start + _WINDOW_CHARS]
        if start + _WINDOW_CHARS >= len(source):
            break
        start += _WINDOW_CHARS - _OVERLAP_CHARS


def extract_requirements(conn: sqlite3.Connection, parsed: parsing.RegulationParseResult) -> tuple[list[ExtractedRequirement], openai.Usage]:
    references = [dict(row) for row in conn.execute("SELECT l.public_ref, q.subject, q.requirement_text FROM regulatory_requirements q JOIN requirement_lineages l ON l.id = q.lineage_id WHERE q.is_current = 1 ORDER BY l.public_ref").fetchall()]
    extracted: list[dict[str, Any]] = []
    usage = openai.Usage()
    reference_text = "\n".join(f"{row['public_ref']} | {row['subject']} | {row['requirement_text']}" for row in references) or "(none)"
    for window in _windows(parsed):
        completion = openai.structured_completion(_EXTRACTION_SYSTEM, f"Existing subject references:\n{reference_text}\n\nRegulation text:\n{window}", _REQUIREMENT_SCHEMA)
        usage = usage.add(completion.usage)
        for raw in completion.value.get("requirements", []):
            extracted.append(_canonical_requirement(raw, parsed.page_count))
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for item in extracted:
        key = (item["subject"], item["source_section"])
        if key not in seen:
            seen.add(key)
            deduplicated.append(item)
    embedding = openai.embed([f"{item['requirement_text']} {item['verbatim_text'] or ''}" for item in deduplicated])
    return [ExtractedRequirement(item, vector) for item, vector in zip(deduplicated, embedding.value)], usage.add(embedding.usage)


def _candidate_rows(conn: sqlite3.Connection, amended_id: str | None) -> list[sqlite3.Row]:
    if not amended_id:
        return []
    return conn.execute(
        """SELECT q.* FROM regulatory_requirements q
           WHERE q.is_current = 1 AND q.lineage_id IN
             (SELECT lineage_id FROM regulatory_requirements WHERE regulation_id = ?)""", (amended_id,)
    ).fetchall()


def _match_lineage(conn: sqlite3.Connection, requirement: ExtractedRequirement, amended_id: str | None) -> str | None:
    candidates = _candidate_rows(conn, amended_id)
    if not candidates:
        return None
    source_matches = [row for row in candidates if row["source_section"] == requirement.data["source_section"]]
    if source_matches:
        return source_matches[0]["lineage_id"]
    subject_matches = [row for row in candidates if row["subject"] == requirement.data["subject"]]
    if subject_matches:
        return subject_matches[0]["lineage_id"]
    candidate_ids = {row["id"]: row["lineage_id"] for row in candidates}
    try:
        rows = conn.execute("SELECT requirement_id, distance FROM vec_requirements WHERE embedding MATCH ? AND k = 40", (sqlite_vec.serialize_float32(requirement.embedding),)).fetchall()
    except sqlite3.Error:
        return None
    for row in rows:
        if row["requirement_id"] in candidate_ids and 1 - float(row["distance"]) >= 0.85:
            return candidate_ids[row["requirement_id"]]
    return None


def _next_public_ref(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT COALESCE(MAX(CAST(SUBSTR(public_ref, 5) AS INTEGER)), 0) + 1 AS next_number FROM requirement_lineages").fetchone()
    return f"REQ-{row['next_number']:03d}"


def persist_requirements(conn: sqlite3.Connection, regulation_id: str, amends_regulation_id: str | None, requirements: list[ExtractedRequirement]) -> int:
    now = _now()
    with conn:
        for extracted in requirements:
            data = extracted.data
            lineage_id = _match_lineage(conn, extracted, amends_regulation_id)
            if lineage_id:
                previous = conn.execute("SELECT id, version FROM regulatory_requirements WHERE lineage_id = ? AND is_current = 1", (lineage_id,)).fetchone()
                version = int(previous["version"]) + 1 if previous else 1
                if previous:
                    conn.execute("UPDATE regulatory_requirements SET is_current = 0 WHERE id = ?", (previous["id"],))
            else:
                lineage_id = uuid.uuid4().hex
                version = 1
                conn.execute("INSERT INTO requirement_lineages (id, public_ref, subject, origin_regulation_id, created_at) VALUES (?, ?, ?, ?, ?)", (lineage_id, _next_public_ref(conn), data["subject"], regulation_id, now))
                previous = None
            requirement_id = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO regulatory_requirements (id, lineage_id, regulation_id, version, requirement_text, verbatim_text, requirement_type, subject, value, value_numeric, value_unit, comparator, condition, exception, source_section, source_page, effective_date, origin, is_current, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', 1, ?)""",
                (requirement_id, lineage_id, regulation_id, version, data["requirement_text"], data["verbatim_text"], data["requirement_type"], data["subject"], data["value"], data["value_numeric"], data["value_unit"], data["comparator"], data["condition"], data["exception"], data["source_section"], data["source_page"], data["effective_date"], now),
            )
            if previous:
                conn.execute("UPDATE regulatory_requirements SET superseded_by = ? WHERE id = ?", (requirement_id, previous["id"]))
            conn.execute("UPDATE requirement_lineages SET subject = ?, current_version_id = ? WHERE id = ?", (data["subject"], requirement_id, lineage_id))
            conn.execute("INSERT INTO fts_requirements (requirement_id, requirement_text, verbatim_text) VALUES (?, ?, ?)", (requirement_id, data["requirement_text"], data["verbatim_text"] or ""))
            conn.execute("INSERT INTO vec_requirements (requirement_id, embedding) VALUES (?, ?)", (requirement_id, sqlite_vec.serialize_float32(extracted.embedding)))
            amended_lineages = {row["lineage_id"] for row in _candidate_rows(conn, amends_regulation_id)}
            for section in data["repeals_sections"]:
                if amended_lineages:
                    placeholders = ",".join("?" * len(amended_lineages))
                    conn.execute(
                        f"UPDATE regulatory_requirements SET is_current = 0 WHERE lineage_id != ? AND lineage_id IN ({placeholders}) AND is_current = 1 AND source_section = ?",
                        [lineage_id, *amended_lineages, section],
                    )
    return len(requirements)


def embed_chunks(chunks: Iterable[Any]) -> tuple[dict[int, list[float]], openai.Usage]:
    eligible = [
        chunk for chunk in chunks
        if chunk.chunk_type != "heading" and len(" ".join(chunk.content.split())) >= 60
    ]
    embedding = openai.embed([
        f"{(chunk.section_path or '').strip()}\n{chunk.content.strip()}" for chunk in eligible
    ])
    return {
        chunk.ordinal: vector for chunk, vector in zip(eligible, embedding.value)
    }, embedding.usage


def _fts_query(query: str) -> str:
    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    return " OR ".join(f'"{term}"' for term in terms[:20])


def _rrf(*legs: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for leg in legs:
        for rank, identifier in enumerate(leg, start=1):
            scores[identifier] = scores.get(identifier, 0) + 1 / (_RRF_OFFSET + rank)
    return scores


def _vector_ids(conn: sqlite3.Connection, table: str, id_column: str, vector: list[float]) -> list[str]:
    try:
        rows = conn.execute(f"SELECT {id_column} FROM {table} WHERE embedding MATCH ? AND k = ?", (sqlite_vec.serialize_float32(vector), _SEARCH_LIMIT)).fetchall()
    except sqlite3.Error:
        return []
    return [row[id_column] for row in rows]


def search(conn: sqlite3.Connection, user: sqlite3.Row, query: str, scope: str, visible_document_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    embedding = openai.embed([query])
    vector = embedding.value[0]
    fts = _fts_query(query)
    chunks: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    if scope in {"chunks", "all"}:
        vector_leg = _vector_ids(conn, "vec_chunks", "chunk_id", vector)
        lexical_rows = conn.execute("SELECT chunk_id FROM fts_chunks WHERE fts_chunks MATCH ? ORDER BY bm25(fts_chunks) LIMIT ?", (fts, _SEARCH_LIMIT)).fetchall() if fts else []
        scores = _rrf(vector_leg, [row["chunk_id"] for row in lexical_rows])
        if visible_document_ids:
            placeholders = ",".join("?" * len(visible_document_ids))
            rows = conn.execute(f"SELECT c.id, c.document_id, d.name AS document_name, c.section_path, c.page_number, c.content FROM document_chunks c JOIN documents d ON d.id = c.document_id WHERE c.id IN ({','.join('?' * len(scores))}) AND c.document_id IN ({placeholders})", [*scores, *visible_document_ids]).fetchall() if scores else []
            by_id = {row["id"]: row for row in rows}
            for identifier, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
                row = by_id.get(identifier)
                if row:
                    chunks.append({"chunk_id": row["id"], "document_id": row["document_id"], "document_name": row["document_name"], "section_path": row["section_path"], "page_number": row["page_number"], "snippet": row["content"][:280], "score": score})
                    if len(chunks) == _RESULT_LIMIT:
                        break
    if scope in {"requirements", "all"}:
        vector_leg = _vector_ids(conn, "vec_requirements", "requirement_id", vector)
        lexical_rows = conn.execute("SELECT requirement_id FROM fts_requirements WHERE fts_requirements MATCH ? ORDER BY bm25(fts_requirements) LIMIT ?", (fts, _SEARCH_LIMIT)).fetchall() if fts else []
        scores = _rrf(vector_leg, [row["requirement_id"] for row in lexical_rows])
        rows = conn.execute(f"SELECT q.id, q.lineage_id, l.public_ref, q.requirement_text, q.source_section FROM regulatory_requirements q JOIN requirement_lineages l ON l.id = q.lineage_id WHERE q.is_current = 1 AND q.id IN ({','.join('?' * len(scores))})", list(scores)).fetchall() if scores else []
        by_id = {row["id"]: row for row in rows}
        for identifier, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
            row = by_id.get(identifier)
            if row:
                requirements.append({"lineage_id": row["lineage_id"], "public_ref": row["public_ref"], "requirement_text": row["requirement_text"], "source_section": row["source_section"], "score": score})
                if len(requirements) == _RESULT_LIMIT:
                    break
    return {"chunks": chunks, "requirements": requirements}
