"""Evidence-grounded minimal-edit recommendations for reviewed impacts."""

from __future__ import annotations

import json
import os
import re
from api.sqlite_driver import sqlite3
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


# --------------------------------------------------------------- decisions --
# One code path for "a person decided about this proposed wording", reachable
# by recommendation id (PATCH /recommendations/{id}) or by impact id
# (POST /impacts/{id}/patch). Both must behave identically, because the second
# exists only so the review screen can address the thing it is looking at.
#
# Accepting is what makes the promise concrete: the approved text is written
# to `document_patches` and nowhere else. Routing both entry points through
# here is what stops a future caller reaching 'resolved' by acceptance without
# ever recording the wording that was accepted.

DecisionStatus = str  # 'accepted' | 'edited' | 'rejected'


def decide(
    conn: sqlite3.Connection,
    recommendation_id: str,
    *,
    status: DecisionStatus,
    actor_id: str,
    edited_text: str | None = None,
    decision_note: str | None = None,
) -> dict[str, Any]:
    """Record a decision, write the patch when accepted, move the impact.

    Returns `{"recommendation_id", "impact_id", "patch_id", "changed"}`.
    Does not commit — the router owns the transaction so the decision, the
    patch and the transition land together or not at all.
    """
    from api.services import patching, workflow

    if status not in {"accepted", "edited", "rejected"}:
        raise ApiError(422, "validation_error", f"Unknown decision '{status}'.")

    row = conn.execute(
        """SELECT r.*, i.id AS impact_id, i.review_status, c.source
             FROM recommendations r
             JOIN impacts i ON i.id = r.impact_id
             JOIN regulatory_changes c ON c.id = i.regulatory_change_id
            WHERE r.id = ?""",
        (recommendation_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Recommendation not found.")

    # Mirrors `capabilities.accept_recommendation` on GET /impacts/{id}: a
    # hypothetical change must not be able to produce a real approved patch.
    if row["source"] == "simulation" and status in {"accepted", "edited"}:
        raise ApiError(409, "conflict", "Promote the simulation before accepting this recommendation.")

    edited_text = edited_text.strip() if edited_text else None
    decision_note = decision_note.strip() if decision_note else None
    if status == "edited" and not edited_text:
        raise ApiError(422, "validation_error", "edited_text is required when marking a recommendation edited.")

    existing_patch = patching.patch_for_impact(conn, row["impact_id"])
    duplicate = (
        row["status"] == status
        and (row["edited_text"] or None) == edited_text
        and (row["decision_note"] or None) == decision_note
        and row["decided_by"] == actor_id
    )
    # A repeated identical decision is a no-op *only* if its consequence is
    # already on record. Re-issuing an accept whose patch is missing must
    # still produce the patch.
    if duplicate and (status == "rejected" or existing_patch is not None):
        return {
            "recommendation_id": recommendation_id,
            "impact_id": row["impact_id"],
            "patch_id": existing_patch["id"] if existing_patch else None,
            "changed": False,
        }

    now = _now()
    conn.execute(
        """INSERT INTO recommendation_decisions
             (id, recommendation_id, status, edited_text, decision_note, decided_by, decided_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (uuid.uuid4().hex, recommendation_id, status, edited_text, decision_note, actor_id, now),
    )
    conn.execute(
        """UPDATE recommendations
              SET status=?, edited_text=?, decision_note=?, decided_by=?, decided_at=?
            WHERE id=?""",
        (status, edited_text, decision_note, actor_id, now, recommendation_id),
    )

    patch_id: str | None = None
    if status in {"accepted", "edited"}:
        patch_id = patching.apply_patch(
            conn,
            row["impact_id"],
            edited_text or row["suggested_text"],
            actor_id,
            recommendation_id=recommendation_id,
        )
    elif existing_patch is not None:
        # Rejecting after an earlier acceptance withdraws the overlay too,
        # otherwise the reader would keep showing wording nobody stands behind.
        patching.revert_patch(conn, existing_patch["id"], actor_id)

    workflow.transition(
        conn,
        row["impact_id"],
        "resolved" if status in {"accepted", "edited"} else "in_review",
        actor_id,
        note=decision_note,
    )
    return {
        "recommendation_id": recommendation_id,
        "impact_id": row["impact_id"],
        "patch_id": patch_id,
        "changed": True,
    }
