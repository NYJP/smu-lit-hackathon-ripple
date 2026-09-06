"""Organization-wide impact review and recommendation generation APIs."""

from __future__ import annotations

import json
from api.sqlite_driver import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import changes as change_service
from api.services import clauses
from api.services import contributions
from api.services import patching
from api.services import recommendations as recommendation_service
from api.services import severity as severity_service
from api.services import workflow

router = APIRouter(prefix="/impacts", tags=["impacts"])

ReviewStatus = Literal[
    "detected",
    "awaiting_review",
    "in_review",
    "needs_analysis",
    "patch_proposed",
    "awaiting_approval",
    "resolved",
    "dismissed",
    "superseded",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImpactPatch(BaseModel):
    """Every field is optional so a caller can reassign or set a due date
    without moving the impact to a different stage."""

    review_status: ReviewStatus | None = None
    assigned_to: str | None = None
    due_date: str | None = None
    note: str | None = None


class PatchIn(BaseModel):
    """The reviewer's decision on the proposed wording.

    `text` is the wording they are approving. Omitted, the recommendation's
    own suggestion is approved verbatim; supplied and different, the decision
    is recorded as `edited` rather than `accepted`, because who wrote the
    final words is part of the record.
    """

    text: str | None = None
    note: str | None = None


def _require_impact(conn: sqlite3.Connection, impact_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM impacts WHERE id = ?", (impact_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Impact not found.")
    return row


def _audit_trail(conn: sqlite3.Connection, impact_id: str) -> list[dict]:
    """Every recorded act on this impact, including acts on its patches.

    `impact_review_events` stays the authoritative narrow record of status
    moves; this is the wider `audit_events` view the review screen shows, so
    a reader can see the approval and the patch it produced as one sequence.

    Ordered by `rowid`, not `id`. Several acts routinely land in one
    transaction — generating wording moves an impact through `in_review` on
    its way to `patch_proposed`, and approving writes a patch and a transition
    together — so their ISO timestamps are identical to the microsecond. `id`
    is a random uuid4 and would shuffle them; `rowid` is insert order, which
    is the order they actually happened in. The same fix applies to the two
    other event listings in this file and to recommendation decisions.
    """
    rows = conn.execute(
        """SELECT a.*, u.display_name AS actor_name
             FROM audit_events a
             LEFT JOIN users u ON u.id = a.actor_id
            WHERE (a.subject_type = 'impact' AND a.subject_id = ?)
               OR (a.subject_type = 'document_patch'
                   AND a.subject_id IN (SELECT id FROM document_patches WHERE impact_id = ?))
            ORDER BY a.created_at, a.rowid""",
        (impact_id, impact_id),
    ).fetchall()
    trail = []
    for row in rows:
        event = dict(row)
        event["detail"] = json.loads(event.pop("detail_json") or "null")
        trail.append(event)
    return trail


def _recommendation(conn: sqlite3.Connection, impact_id: str) -> dict | None:
    row = conn.execute(
        """SELECT r.*, u.display_name AS decided_by_name
           FROM recommendations r
           LEFT JOIN users u ON u.id = r.decided_by
           WHERE r.impact_id = ?""",
        (impact_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["source_citations"] = json.loads(result["source_citations"] or "[]")
    result["decision_history"] = [
        dict(item) for item in conn.execute(
            """SELECT rd.*, u.display_name AS decided_by_name
               FROM recommendation_decisions rd
               JOIN users u ON u.id = rd.decided_by
               WHERE rd.recommendation_id = ?
               ORDER BY rd.decided_at, rd.rowid""",
            (row["id"],),
        ).fetchall()
    ]
    return result


@router.get("")
def list_impacts(
    impact_level: Literal["high", "medium", "low", "none"] | None = None,
    review_status: ReviewStatus | None = None,
    open_only: bool = False,
    document_id: str | None = None,
    owner_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    filters = ["1 = 1"]
    values: list[object] = []
    for clause, value in (
        ("i.impact_level = ?", impact_level),
        ("i.review_status = ?", review_status),
        ("i.document_id = ?", document_id),
        ("d.owner_id = ?", owner_id),
    ):
        if value is not None:
            filters.append(clause)
            values.append(value)
    if open_only:
        clause, open_values = workflow.open_status_sql("i.review_status")
        filters.append(clause)
        values.extend(open_values)
    where = " AND ".join(filters)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM impacts i JOIN documents d ON d.id=i.document_id WHERE {where}",
        values,
    ).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT i.*, d.name AS document_name, d.doc_type,
                   u.id AS owner_id, u.display_name AS owner_name,
                   c.summary AS change_summary, c.source, c.simulation_id,
                   c.change_type, c.effective_date,
                   chunk.section_path, chunk.section_title, chunk.ordinal AS chunk_ordinal,
                   chunk.content AS chunk_content, chunk.page_number
            FROM impacts i
            JOIN documents d ON d.id=i.document_id
            JOIN users u ON u.id=d.owner_id
            JOIN regulatory_changes c ON c.id=i.regulatory_change_id
            JOIN document_chunks chunk ON chunk.id=i.document_chunk_id
            WHERE {where}
            ORDER BY CASE i.impact_level WHEN 'high' THEN 0 WHEN 'medium' THEN 1
                     WHEN 'low' THEN 2 ELSE 3 END, i.created_at DESC, i.id
            LIMIT ? OFFSET ?""",
        [*values, limit, offset],
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        # `severity` is the display value (may escalate a stored 'high' to
        # 'critical'); `impact_level` stays exactly what was stored.
        item["severity"] = severity_service.derive_severity(row, row)
        item["review_status_label"] = workflow.STATUS_LABELS.get(row["review_status"], row["review_status"])
        item["contributor"] = contributions.for_span(
            conn, row["document_chunk_id"], row["conflicting_start"], row["conflicting_end"]
        )
        # Where the passage sits and what it says, decided in one place so the
        # queue, the review screen and the reader cannot label it differently.
        item["clause_label"] = clauses.clause_label(
            {
                "section_path": row["section_path"],
                "section_title": row["section_title"],
                "content": row["chunk_content"],
                "ordinal": row["chunk_ordinal"],
            },
            position=row["conflicting_start"],
        )
        item["clause_excerpt"] = clauses.clause_excerpt(
            row["chunk_content"], row["conflicting_start"], row["conflicting_end"]
        )
        # The full chunk text was only needed to derive those two.
        item.pop("chunk_content", None)
        items.append(item)
    # Re-sort on derived severity: SQL ordered by the stored level, which
    # cannot see the critical escalation.
    items.sort(
        key=lambda entry: (
            -severity_service.SEVERITY_RANK.get(entry["severity"], 0),
            entry.get("created_at") or "",
        )
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{impact_id}")
def get_impact(
    impact_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    impact = _require_impact(conn, impact_id)
    change = conn.execute(
        "SELECT * FROM regulatory_changes WHERE id = ?", (impact["regulatory_change_id"],)
    ).fetchone()
    previous, proposed = change_service.get_change_requirement_pair(conn, change)
    dependency = conn.execute(
        "SELECT * FROM dependencies WHERE id = ?", (impact["dependency_id"],)
    ).fetchone()
    chunk = conn.execute(
        "SELECT * FROM document_chunks WHERE id = ?", (impact["document_chunk_id"],)
    ).fetchone()
    document = conn.execute(
        """SELECT d.*, u.display_name AS owner_name
           FROM documents d JOIN users u ON u.id=d.owner_id WHERE d.id=?""",
        (impact["document_id"],),
    ).fetchone()
    collaborators = conn.execute(
        """SELECT u.id, u.display_name, dc.access
           FROM document_collaborators dc JOIN users u ON u.id=dc.user_id
           WHERE dc.document_id=? ORDER BY u.display_name COLLATE NOCASE""",
        (impact["document_id"],),
    ).fetchall()
    requirement = proposed or previous or {}
    regulation_id = requirement.get("regulation_id")
    if regulation_id is None:
        origin = conn.execute(
            "SELECT origin_regulation_id FROM requirement_lineages WHERE id=?", (change["lineage_id"],)
        ).fetchone()
        regulation_id = origin["origin_regulation_id"] if origin else None
    regulation = conn.execute("SELECT * FROM regulations WHERE id=?", (regulation_id,)).fetchone() if regulation_id else None
    review_history = [
        dict(row) for row in conn.execute(
            """SELECT e.*, u.display_name AS changed_by_name
               FROM impact_review_events e JOIN users u ON u.id=e.changed_by
               WHERE e.impact_id=? ORDER BY e.changed_at, e.rowid""",
            (impact_id,),
        ).fetchall()
    ]
    recommendation = _recommendation(conn, impact_id)
    patch = patching.patch_for_impact(conn, impact_id)
    # Everything else on this document that still needs a person, so the
    # review screen can offer "next affected clause" without a second call.
    open_clause, open_values = workflow.open_status_sql("i.review_status")
    siblings = [
        dict(row) for row in conn.execute(
            f"""SELECT i.id, i.impact_level, i.confidence, i.review_status,
                       i.conflicting_span, i.conflicting_start, i.conflicting_end,
                       chunk.section_path, chunk.section_title, chunk.content,
                       chunk.ordinal, c.change_type, c.effective_date
                  FROM impacts i
                  JOIN document_chunks chunk ON chunk.id = i.document_chunk_id
                  JOIN regulatory_changes c ON c.id = i.regulatory_change_id
                 WHERE i.document_id = ? AND i.id <> ? AND i.impact_level <> 'none'
                   AND {open_clause}
                 ORDER BY chunk.ordinal, i.created_at""",
            [impact["document_id"], impact_id, *open_values],
        ).fetchall()
    ]
    for sibling in siblings:
        sibling["severity"] = severity_service.derive_severity(sibling, sibling)
        sibling["review_status_label"] = workflow.STATUS_LABELS.get(
            sibling["review_status"], sibling["review_status"]
        )
        sibling["clause_label"] = clauses.clause_label(
            sibling, position=sibling["conflicting_start"]
        )
        sibling.pop("content", None)
    return {
        "impact": {
            **dict(impact),
            "severity": severity_service.derive_severity(impact, change),
            "clause_label": clauses.clause_label(chunk, position=impact["conflicting_start"]),
            "review_status_label": workflow.STATUS_LABELS.get(
                impact["review_status"], impact["review_status"]
            ),
        },
        "change": dict(change),
        "regulation": dict(regulation) if regulation else None,
        "previous_requirement": previous,
        "new_requirement": proposed,
        "dependency": dict(dependency),
        "document": {
            **dict(document),
            "owner": {"id": document["owner_id"], "display_name": document["owner_name"]},
            "collaborators": [dict(row) for row in collaborators],
        },
        "chunk": dict(chunk),
        "contributor": contributions.for_span(
            conn, chunk["id"], impact["conflicting_start"], impact["conflicting_end"]
        ),
        "recommendation": recommendation,
        "patch": patch,
        "review_history": review_history,
        "audit_trail": _audit_trail(conn, impact_id),
        "other_open_impacts": siblings,
        "capabilities": {
            "change_review_status": True,
            "generate_recommendation": True,
            "decide_recommendation": True,
            "accept_recommendation": change["source"] != "simulation",
            # Approving needs both a proposal to approve and a state the
            # machine will actually let us leave for 'resolved'.
            "approve_patch": (
                change["source"] != "simulation"
                and recommendation is not None
                and workflow.can_transition(impact["review_status"], "resolved")
            ),
            "revert_patch": patch is not None,
            # Drives which decision buttons the review screen enables, so the
            # UI never offers a transition the state machine would refuse.
            "allowed_transitions": sorted(
                workflow.ALLOWED_TRANSITIONS.get(impact["review_status"], frozenset())
            ),
        },
    }


@router.patch("/{impact_id}")
def patch_impact(
    impact_id: str,
    payload: ImpactPatch,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    current = _require_impact(conn, impact_id)
    # services/workflow.py owns the write: it validates the transition, records
    # who did it, and notifies the document's stakeholders. Nothing else may
    # set review_status directly.
    workflow.transition(
        conn,
        impact_id,
        payload.review_status or current["review_status"],
        user["id"],
        note=payload.note,
        assigned_to=payload.assigned_to,
        due_date=payload.due_date,
    )
    conn.commit()
    return get_impact(impact_id, conn, user)


@router.post("/{impact_id}/patch", status_code=201)
def approve_patch(
    impact_id: str,
    payload: PatchIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    """Approve the proposed wording for this impact.

    The single most important guarantee in the product runs through here:
    approving writes a `document_patches` row and nothing else. It does not
    update `document_chunks.content` and it does not open the file on disk —
    see api/services/patching.py, and tests/test_patching.py, which proves it.

    The decision, the patch and the move to `resolved` are one transaction:
    a half-approved impact — resolved with no recorded wording, or a patch
    with no decision behind it — would be worse than a failed request.
    """
    _require_impact(conn, impact_id)
    recommendation = conn.execute(
        "SELECT id, suggested_text FROM recommendations WHERE impact_id = ?", (impact_id,)
    ).fetchone()
    if recommendation is None:
        raise ApiError(
            409,
            "conflict",
            "Generate proposed wording before approving a patch for this impact.",
        )
    text = (payload.text or "").strip() or recommendation["suggested_text"]
    # Approving the suggestion unchanged and rewriting it are different acts,
    # and the decision record keeps them apart.
    status = "accepted" if text.strip() == (recommendation["suggested_text"] or "").strip() else "edited"
    result = recommendation_service.decide(
        conn,
        recommendation["id"],
        status=status,
        actor_id=user["id"],
        edited_text=text if status == "edited" else None,
        decision_note=payload.note,
    )
    conn.commit()
    return {"patch_id": result["patch_id"], **get_impact(impact_id, conn, user)}


@router.delete("/{impact_id}/patch")
def revert_patch(
    impact_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    """Withdraw the approved wording and reopen the impact.

    The patch row is kept and marked reverted rather than deleted — an
    approval that was later withdrawn is exactly the kind of thing the audit
    trail exists to remember.
    """
    _require_impact(conn, impact_id)
    patch = patching.patch_for_impact(conn, impact_id)
    if patch is None:
        raise ApiError(404, "not_found", "No approved patch to revert on this impact.")
    patching.revert_patch(conn, patch["id"], user["id"])
    workflow.transition(conn, impact_id, "in_review", user["id"], note="Approved wording withdrawn.")
    conn.commit()
    return get_impact(impact_id, conn, user)


@router.post("/{impact_id}/recommendation", status_code=201)
def generate_recommendation(
    impact_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
):
    impact = _require_impact(conn, impact_id)
    recommendation, usage = recommendation_service.generate(conn, impact_id)
    # Proposing wording is itself an act of review, so the impact advances.
    # This is also what makes a later Accept legal: 'resolved' is reachable
    # from 'patch_proposed', but deliberately not straight from 'detected'.
    #
    # `patch_proposed` is only reachable from `in_review`, so a still-untouched
    # impact passes through it rather than teleporting. That is the honest
    # record as well as the legal one: someone did just look at this clause.
    current = impact["review_status"]
    if current in {"detected", "awaiting_review", "needs_analysis", "in_review"}:
        if current != "in_review":
            workflow.transition(
                conn, impact_id, "in_review", _user["id"], notify_stakeholders=False
            )
        workflow.transition(
            conn, impact_id, "patch_proposed", _user["id"], notify_stakeholders=False
        )
    conn.commit()
    return {"recommendation": recommendation, "usage": usage.as_dict()}
