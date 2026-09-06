"""Regulatory diff classification and evidence-grounded impact analysis."""

from __future__ import annotations

import json
import os
import re
from api.sqlite_driver import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from api.services import changes as change_utils
from api.services import openai

_BATCH_SIZE = 6
_LEVELS = {"none", "low", "medium", "high"}
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20",
}
_UNIT_ALIASES = {
    "gram": "g", "grams": "g", "gramme": "g", "grammes": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg",
    "milligram": "mg", "milligrams": "mg", "mg": "mg",
    "day": "day", "days": "day", "month": "month", "months": "month",
    "year": "year", "years": "year", "yr": "year", "yrs": "year",
    "hour": "hour", "hours": "hour", "minute": "minute", "minutes": "minute",
    "second": "second", "seconds": "second", "week": "week", "weeks": "week",
    "percent": "%", "percentage": "%", "percentages": "%",
    "dollar": "dollar", "dollars": "dollar",
}

_IMPACT_SYSTEM = (
    "Classify how a changed regulatory requirement affects each dependent internal passage. "
    "Use high when the passage is contradicted or contains a superseded instruction/value; "
    "medium when it requires substantive review or implementation changes; low when the link "
    "is indirect or editorial; none when the passage remains correct. Evidence_quote must be "
    "an exact substring of the supplied passage or null. Return one decision per dependency."
)

_IMPACT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["decisions"],
    "properties": {"decisions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["dependency_id", "level", "reason", "evidence_quote", "confidence"],
        "properties": {
            "dependency_id": {"type": "string"},
            "level": {"type": "string", "enum": ["none", "low", "medium", "high"]},
            "reason": {"type": "string"},
            "evidence_quote": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }}},
}


@dataclass(frozen=True)
class ImpactAnalysisResult:
    impacts_created: int = 0
    impacts_evaluated: int = 0
    cache_hits: int = 0
    counts: dict[str, int] = field(
        default_factory=lambda: {"high": 0, "medium": 0, "low": 0, "none": 0}
    )
    usage: openai.Usage = openai.Usage()

    def as_dict(self) -> dict[str, Any]:
        return {
            "impacts_created": self.impacts_created,
            "impacts_evaluated": self.impacts_evaluated,
            "cache_hits": self.cache_hits,
            "counts": self.counts,
            "usage": self.usage.as_dict(),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_value(row: sqlite3.Row | dict[str, Any] | None, key: str) -> Any:
    if row is None:
        return None
    return row[key] if key in row.keys() else None


def _canonical_token(token: str) -> str:
    normalized = unicodedata.normalize("NFKC", token).casefold()
    return _NUMBER_WORDS.get(normalized, _UNIT_ALIASES.get(normalized, normalized))


def _tokens_with_offsets(text: str) -> list[tuple[str, int, int]]:
    return [
        (_canonical_token(match.group(0)), match.start(), match.end())
        for match in re.finditer(r"[\w]+|%", text, flags=re.UNICODE)
    ]


def normalized_literal(value: str | None) -> str | None:
    if value is None:
        return None
    tokens = [token for token, _start, _end in _tokens_with_offsets(str(value))]
    return " ".join(tokens) or None


def locate_literal(content: str, literal: str | None) -> tuple[str | None, int | None, int | None]:
    target = normalized_literal(literal)
    if not target:
        return None, None, None
    wanted = target.split()
    source = _tokens_with_offsets(content)
    for start_index in range(0, len(source) - len(wanted) + 1):
        if [item[0] for item in source[start_index:start_index + len(wanted)]] == wanted:
            start = source[start_index][1]
            end = source[start_index + len(wanted) - 1][2]
            return content[start:end], start, end
    return None, None, None


def _plain_text(value: Any) -> str:
    return " ".join(re.findall(r"[\w]+", unicodedata.normalize("NFKC", str(value or "")).casefold()))


def change_fields(
    previous: sqlite3.Row | dict[str, Any] | None,
    proposed: dict[str, Any],
    op: str = "modify",
) -> tuple[str, str | None, str | None, str]:
    """Classify a requirement transition without persisting it."""
    subject = str(proposed.get("subject") or _row_value(previous, "subject") or "requirement")
    subject_label = subject.replace("_", " ").title()
    if op == "add":
        return "added", None, proposed.get("value"), f"{subject_label}: added"
    if op in {"remove", "repeal"}:
        return "removed", _row_value(previous, "value"), None, f"{subject_label}: removed"

    old_value = _row_value(previous, "value")
    new_value = proposed.get("value", old_value)
    numeric_changed = proposed.get("value_numeric", _row_value(previous, "value_numeric")) != _row_value(previous, "value_numeric")
    unit_changed = normalized_literal(proposed.get("value_unit", _row_value(previous, "value_unit"))) != normalized_literal(_row_value(previous, "value_unit"))
    comparator_changed = proposed.get("comparator", _row_value(previous, "comparator")) != _row_value(previous, "comparator")
    if normalized_literal(old_value) != normalized_literal(new_value) or numeric_changed or unit_changed or comparator_changed:
        unit = proposed.get("value_unit", _row_value(previous, "value_unit"))
        kind = "duration" if normalized_literal(unit) in {"day", "month", "year"} else "threshold"
        return kind, old_value, new_value, f"{subject_label}: {old_value or 'unspecified'} → {new_value or 'unspecified'}"

    for key, kind in (("exception", "exception"), ("condition", "scope"), ("effective_date", "effective_date")):
        old_field = _row_value(previous, key)
        new_field = proposed.get(key, old_field)
        if _plain_text(new_field) != _plain_text(old_field):
            return kind, old_field, new_field, f"{subject_label}: {kind.replace('_', ' ')} changed"

    old_text = str(_row_value(previous, "requirement_text") or "")
    new_text = str(proposed.get("requirement_text", old_text) or "")
    if old_text != new_text:
        if _plain_text(old_text) == _plain_text(new_text) or SequenceMatcher(None, _plain_text(old_text), _plain_text(new_text)).ratio() >= 0.98:
            return "editorial", None, None, f"{subject_label}: editorial update"
        kind = "definition" if _row_value(previous, "requirement_type") == "definition" else "obligation"
        return kind, old_text, new_text, f"{subject_label}: {kind} changed"
    return "editorial", None, None, f"{subject_label}: editorial update"


def classify(
    content: str,
    old_value: str | None,
    new_value: str | None,
    relationship: str,
) -> tuple[str, str, str | None, int | None, int | None]:
    """Deterministic literal override retained for compatibility and safety."""
    if normalized_literal(old_value) != normalized_literal(new_value):
        span, start, end = locate_literal(content, old_value)
        if span is not None:
            return "high", "The passage contains the superseded value.", span, start, end
    if relationship == "references":
        return "medium", "The passage defers to the changed requirement.", None, None, None
    return "low", "The passage depends on the changed requirement and requires review.", None, None, None


def _cache_key_parts(
    previous: dict[str, Any] | None,
    proposed: dict[str, Any] | None,
    row: sqlite3.Row,
) -> tuple[str, str, str]:
    return (
        change_utils.requirement_content_hash(previous),
        change_utils.requirement_content_hash(proposed),
        change_utils.document_chunk_hash(row),
    )


def _read_cache(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    previous_hash: str,
    new_hash: str,
    chunk_hash: str,
    model: str,
) -> dict[str, Any] | None:
    cached = conn.execute(
        """SELECT result_json FROM impact_cache
           WHERE dependency_id = ? AND previous_requirement_hash = ?
             AND new_requirement_hash = ? AND document_chunk_hash = ? AND model = ?""",
        (row["dependency_id"], previous_hash, new_hash, chunk_hash, model),
    ).fetchone()
    if cached is None:
        return None
    try:
        value = json.loads(cached["result_json"])
        return value if value.get("level") in _LEVELS else None
    except (TypeError, json.JSONDecodeError):
        return None


def _write_cache(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    previous_hash: str,
    new_hash: str,
    chunk_hash: str,
    model: str,
    result: dict[str, Any],
    usage: openai.Usage,
) -> None:
    now = _now()
    conn.execute(
        """INSERT INTO impact_cache
           (dependency_id, previous_requirement_hash, new_requirement_hash,
            document_chunk_hash, model, result_json, prompt_tokens,
            completion_tokens, estimated_cost_usd, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(dependency_id, previous_requirement_hash, new_requirement_hash,
                       document_chunk_hash, model)
           DO UPDATE SET result_json=excluded.result_json,
                         prompt_tokens=excluded.prompt_tokens,
                         completion_tokens=excluded.completion_tokens,
                         estimated_cost_usd=excluded.estimated_cost_usd,
                         updated_at=excluded.updated_at""",
        (
            row["dependency_id"], previous_hash, new_hash, chunk_hash, model,
            json.dumps(result), usage.prompt_tokens, usage.completion_tokens,
            usage.estimated_cost_usd, now, now,
        ),
    )


def _locate_evidence(content: str, quote: str | None) -> tuple[str | None, int | None, int | None]:
    if not quote:
        return None, None, None
    start = content.find(quote)
    if start < 0:
        folded_start = content.casefold().find(quote.casefold())
        if folded_start < 0:
            raise openai.ExternalServiceError("Impact evidence was not found in the supplied passage.")
        start = folded_start
    end = start + len(quote)
    return content[start:end], start, end


def _write_impact(
    conn: sqlite3.Connection,
    change_id: str,
    row: sqlite3.Row,
    result: dict[str, Any],
    scan_id: str | None = None,
) -> bool:
    span, start, end = _locate_evidence(row["content"], result.get("evidence_quote"))
    existing = conn.execute(
        "SELECT id FROM impacts WHERE regulatory_change_id = ? AND dependency_id = ?",
        (change_id, row["dependency_id"]),
    ).fetchone()
    impact_id = existing["id"] if existing else uuid.uuid4().hex
    conn.execute(
        """INSERT INTO impacts
           (id, regulatory_change_id, dependency_id, document_id, document_chunk_id,
            impact_level, confidence, reason, conflicting_span, conflicting_start,
            conflicting_end, created_by_scan_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(regulatory_change_id, dependency_id) DO UPDATE SET
             impact_level=excluded.impact_level, confidence=excluded.confidence,
             reason=excluded.reason, conflicting_span=excluded.conflicting_span,
             conflicting_start=excluded.conflicting_start,
             conflicting_end=excluded.conflicting_end,
             created_by_scan_id=COALESCE(impacts.created_by_scan_id, excluded.created_by_scan_id)""",
        (
            impact_id, change_id, row["dependency_id"], row["document_id"],
            row["document_chunk_id"], result["level"], float(result["confidence"]),
            str(result["reason"]), span, start, end, scan_id, _now(),
        ),
    )
    return existing is None


def _model_decisions(
    previous: dict[str, Any] | None,
    proposed: dict[str, Any] | None,
    rows: list[sqlite3.Row],
) -> tuple[list[dict[str, Any]], openai.OpenAIResult[dict[str, Any]]]:
    passages = "\n\n".join(
        f"Dependency {row['dependency_id']} | relationship {row['relationship_type']}\n"
        f"Passage:\n{row['content']}"
        for row in rows
    )
    completion = openai.structured_completion(
        _IMPACT_SYSTEM,
        f"Previous requirement:\n{json.dumps(previous, default=str)}\n\n"
        f"New requirement:\n{json.dumps(proposed, default=str)}\n\n{passages}",
        _IMPACT_SCHEMA,
        model=os.environ.get("RIPPLE_REASONING_MODEL", "gpt-5"),
        schema_name="impact_decisions",
    )
    permitted = {row["dependency_id"] for row in rows}
    decisions = [
        item for item in completion.value.get("decisions", [])
        if item.get("dependency_id") in permitted
    ]
    if len(decisions) != len(permitted) or {item["dependency_id"] for item in decisions} != permitted:
        raise openai.ExternalServiceError("Impact output did not contain exactly one decision per dependency.")
    return decisions, completion


def analyse_change(
    conn: sqlite3.Connection,
    change_id: str,
    *,
    dependency_ids: set[str] | None = None,
    scan_id: str | None = None,
) -> ImpactAnalysisResult:
    """Evaluate active dependencies without committing the caller's transaction."""
    change = conn.execute("SELECT * FROM regulatory_changes WHERE id = ?", (change_id,)).fetchone()
    if change is None:
        return ImpactAnalysisResult()
    previous, proposed = change_utils.get_change_requirement_pair(conn, change)
    values: list[Any] = [change["lineage_id"]]
    dependency_filter = ""
    if dependency_ids is not None:
        if not dependency_ids:
            return ImpactAnalysisResult()
        dependency_filter = f" AND dep.id IN ({','.join('?' * len(dependency_ids))})"
        values.extend(sorted(dependency_ids))
    rows = conn.execute(
        """SELECT dep.id AS dependency_id, dep.document_id, dep.document_chunk_id,
                  dep.relationship_type, dep.confidence AS dependency_confidence,
                  c.ordinal, c.section_path, c.page_number, c.content
           FROM dependencies dep
           JOIN document_chunks c ON c.id = dep.document_chunk_id
           WHERE dep.lineage_id = ? AND dep.status = 'active'""" + dependency_filter,
        values,
    ).fetchall()

    model = os.environ.get("RIPPLE_REASONING_MODEL", "gpt-5")
    results: dict[str, tuple[dict[str, Any], str, tuple[str, str, str], openai.Usage, bool]] = {}
    uncached: list[sqlite3.Row] = []
    cache_hits = 0
    usage = openai.Usage()
    old_value = change["old_value"]
    new_value = change["new_value"]

    for row in rows:
        hashes = _cache_key_parts(previous, proposed, row)
        literal_span, literal_start, literal_end = (None, None, None)
        if normalized_literal(old_value) != normalized_literal(new_value):
            literal_span, literal_start, literal_end = locate_literal(row["content"], old_value)
        selected_model = "literal_override-v1" if literal_span is not None else model
        cached = _read_cache(conn, row, *hashes, selected_model)
        if cached is not None:
            results[row["dependency_id"]] = (cached, selected_model, hashes, openai.Usage(), True)
            cache_hits += 1
            continue
        if literal_span is not None:
            result = {
                "dependency_id": row["dependency_id"],
                "level": "high",
                "reason": "The passage contains the superseded value.",
                "evidence_quote": row["content"][literal_start:literal_end],
                "confidence": 1.0,
            }
            results[row["dependency_id"]] = (result, selected_model, hashes, openai.Usage(), False)
        else:
            uncached.append(row)

    for start in range(0, len(uncached), _BATCH_SIZE):
        batch = uncached[start:start + _BATCH_SIZE]
        decisions, completion = _model_decisions(previous, proposed, batch)
        usage = usage.add(completion.usage)
        by_id = {row["dependency_id"]: row for row in batch}
        for decision in decisions:
            row = by_id[decision["dependency_id"]]
            _locate_evidence(row["content"], decision.get("evidence_quote"))
            item_count = max(1, len(decisions))
            allocated_cost = (
                None if completion.usage.estimated_cost_usd is None
                else completion.usage.estimated_cost_usd / item_count
            )
            allocated_usage = openai.Usage(
                completion.usage.prompt_tokens // item_count,
                completion.usage.completion_tokens // item_count,
                completion.usage.total_tokens // item_count,
                allocated_cost,
            )
            results[row["dependency_id"]] = (
                decision, model, _cache_key_parts(previous, proposed, row), allocated_usage, False
            )

    created = 0
    counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
    by_id = {row["dependency_id"]: row for row in rows}
    for dependency_id, (result, selected_model, hashes, call_usage, was_cached) in results.items():
        row = by_id[dependency_id]
        if not was_cached:
            _write_cache(conn, row, *hashes, selected_model, result, call_usage)
        created += int(_write_impact(conn, change_id, row, result, scan_id))
        counts[result["level"]] += 1

    if dependency_ids is None:
        conn.execute(
            "UPDATE regulatory_changes SET analysis_status = 'complete' WHERE id = ?", (change_id,)
        )
    return ImpactAnalysisResult(created, len(results), cache_hits, counts, usage)


def visible_change(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    change_id: str,
) -> sqlite3.Row | None:
    """All authenticated accounts can inspect every organization change."""
    del user
    return conn.execute("SELECT * FROM regulatory_changes WHERE id = ?", (change_id,)).fetchone()
