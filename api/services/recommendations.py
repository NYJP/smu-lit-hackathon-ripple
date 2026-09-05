"""Evidence-grounded minimal-edit recommendations for reviewed impacts."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from api.errors import ApiError
from api.services import changes as change_utils
from api.services import impact
from api.services import openai

_SYSTEM = (
    "Propose the smallest edit that makes the affected internal text consistent with the "
    "new regulatory requirement. Preserve style, defined terms, and unaffected wording. "
    "Do not add obligations not grounded in the supplied requirement. Cite the regulatory "
    "section and the internal evidence passage used."
)

_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["replacement_text", "rationale", "source_citations"],
    "properties": {
        "replacement_text": {"type": "string"},
        "rationale": {"type": "string"},
        "source_citations": {
            "type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["source", "section", "quote"],
                "properties": {
                    "source": {"type": "string", "enum": ["regulation", "document"]},
                    "section": {"type": ["string", "null"]},
                    "quote": {"type": "string"},
                },
            },
        },
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_case_insensitive(text: str, old: str | None, new: str | None) -> str:
    if not old or new is None:
        return text
    _span, start, end = impact.locate_literal(text, old)
    if start is not None and end is not None:
        return text[:start] + new + text[end:]
    return re.sub(re.escape(old), new, text, count=1, flags=re.IGNORECASE)


def generate(
    conn: sqlite3.Connection,
    impact_id: str,
) -> tuple[dict[str, Any], openai.Usage]:
    row = conn.execute(
        """SELECT i.*, dep.relationship_type, dep.evidence_span,
                  chunk.content, chunk.section_path, chunk.page_number,
                  doc.name AS document_name, change.source, change.old_value,
                  change.new_value, change.summary, change.simulation_id
           FROM impacts i
           JOIN dependencies dep ON dep.id = i.dependency_id
           JOIN document_chunks chunk ON chunk.id = i.document_chunk_id
           JOIN documents doc ON doc.id = i.document_id
           JOIN regulatory_changes change ON change.id = i.regulatory_change_id
           WHERE i.id = ?""",
        (impact_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Impact not found.")
    change = conn.execute(
        "SELECT * FROM regulatory_changes WHERE id = ?", (row["regulatory_change_id"],)
    ).fetchone()
    previous, proposed = change_utils.get_change_requirement_pair(conn, change)
    current_text = row["conflicting_span"] or row["evidence_span"] or row["content"]
    generation_method = "model"
    try:
        completion = openai.structured_completion(
            _SYSTEM,
            f"Previous requirement:\n{json.dumps(previous, default=str)}\n\n"
            f"New requirement:\n{json.dumps(proposed, default=str)}\n\n"
            f"Affected document: {row['document_name']}\n"
            f"Section: {row['section_path']}\nImpact reason: {row['reason']}\n\n"
            f"Current affected text:\n{current_text}",
            _SCHEMA,
            model=os.environ.get("RIPPLE_REASONING_MODEL", "gpt-5"),
            schema_name="recommendation",
        )
        generated = completion.value
        citations = generated["source_citations"]
        sources = {citation["source"] for citation in citations}
        regulatory_source = "\n".join(
            str((proposed or previous or {}).get(field) or "")
            for field in ("requirement_text", "verbatim_text")
        )
        for citation in citations:
            quote = str(citation["quote"]).strip()
            source_text = row["content"] if citation["source"] == "document" else regulatory_source
            if not quote or quote.casefold() not in source_text.casefold():
                raise openai.ExternalServiceError(
                    "Recommendation citations were not grounded in the supplied source text."
                )
        if not {"document", "regulation"}.issubset(sources):
            raise openai.ExternalServiceError(
                "Recommendation output did not cite both the document and regulation."
            )
        usage = completion.usage
    except openai.ExternalServiceError:
        generation_method = "deterministic_fallback"
        generated = {
            "replacement_text": _replace_case_insensitive(current_text, row["old_value"], row["new_value"]),
            "rationale": (
                "Model generation was unavailable. This fallback only replaces the literal "
                "superseded value and requires manual review."
            ),
            "source_citations": [
                {
                    "source": "regulation",
                    "section": (proposed or previous or {}).get("source_section"),
                    "quote": str((proposed or previous or {}).get("verbatim_text") or (proposed or previous or {}).get("requirement_text") or ""),
                },
                {"source": "document", "section": row["section_path"], "quote": current_text},
            ],
        }
        usage = openai.Usage()

    replacement = str(generated["replacement_text"]).strip()
    if not replacement:
        raise ApiError(502, "external_service_error", "Recommendation generation returned empty text.")
    existing = conn.execute("SELECT id FROM recommendations WHERE impact_id = ?", (impact_id,)).fetchone()
    recommendation_id = existing["id"] if existing else uuid.uuid4().hex
    values = (
        current_text,
        replacement,
        str(generated["rationale"]).strip(),
        int(row["source"] == "simulation"),
        json.dumps(generated["source_citations"]),
        generation_method,
    )
    if existing:
        conn.execute(
            """UPDATE recommendations
               SET current_text=?, suggested_text=?, rationale=?, requires_human_decision=?,
                   source_citations=?, generation_method=?, status='proposed', edited_text=NULL,
                   decision_note=NULL, decided_by=NULL, decided_at=NULL
               WHERE id=?""",
            (*values, recommendation_id),
        )
    else:
        conn.execute(
            """INSERT INTO recommendations
               (id, impact_id, current_text, suggested_text, rationale,
                requires_human_decision, source_citations, generation_method, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (recommendation_id, impact_id, *values, _now()),
        )
    result = dict(conn.execute("SELECT * FROM recommendations WHERE id = ?", (recommendation_id,)).fetchone())
    result["source_citations"] = json.loads(result["source_citations"] or "[]")
    return result, usage
