"""Accepted wording, stored as an overlay — never as an edit to the document.

This module exists to keep one promise literally true: **Ripple never edits
your documents.** When a reviewer approves proposed wording, nothing is
written to `document_chunks.content` and nothing is written to the file on
disk. The accepted text lands in `document_patches` as a span replacement,
and the reader composes the two at render time.

That distinction is not cosmetic. The uploaded file is the organisation's
record of what its policy actually said on a given date; a tool that quietly
rewrites it destroys the only copy of that fact. A patch is a *proposal that
was approved*, which is a different thing from the document itself, and the
two must stay separately readable — including after the approval turns out to
have been wrong.

So, the rule this module enforces, and which `tests/test_patching.py` pins:

    apply_patch() issues exactly one INSERT, into document_patches.
    It must never UPDATE document_chunks, and never open the file.

Every span is resolved to concrete `(char_start, char_end)` offsets into the
chunk's content, so the overlay is always unambiguous — a patch with a null
span would leave the reader guessing which words it replaced.

Convention, as everywhere else in `api/services`: nothing here commits. The
router owns the transaction so the patch, the recommendation decision and the
workflow transition land together or not at all.
"""

from __future__ import annotations

from api.sqlite_driver import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from api.errors import ApiError
from api.services import impact as impact_service
from api.services import workflow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_span(
    content: str,
    *,
    start: int | None,
    end: int | None,
    fallback_text: str | None = None,
) -> tuple[int, int]:
    """The exact `(start, end)` of the chunk text a patch replaces.

    Prefers the impact's own recorded conflict span, which came from the
    analysis that found the problem. Falls back to locating the wording the
    recommendation was generated against, and finally to the whole chunk —
    which is correct rather than lazy: if we cannot say which sentence was
    superseded, the honest overlay replaces the passage the reviewer was shown.
    """
    length = len(content)
    if start is not None and end is not None and 0 <= start < end <= length:
        return start, end
    if fallback_text:
        _span, located_start, located_end = impact_service.locate_literal(content, fallback_text)
        if located_start is not None and located_end is not None:
            return located_start, located_end
    return 0, length


def _overlapping_patch(
    conn: sqlite3.Connection,
    chunk_id: str,
    start: int,
    end: int,
    *,
    ignore_impact_id: str | None,
) -> sqlite3.Row | None:
    """An applied patch whose span collides with `[start, end)`.

    Two approved patches over the same words cannot both be rendered, so the
    second one is refused rather than silently winning. Adjacent spans that
    merely touch (`a.end == b.start`) do not overlap.
    """
    rows = conn.execute(
        """SELECT p.id, p.impact_id, p.char_start, p.char_end
             FROM document_patches p
            WHERE p.document_chunk_id = ? AND p.status = 'applied'""",
        (chunk_id,),
    ).fetchall()
    for row in rows:
        if ignore_impact_id is not None and row["impact_id"] == ignore_impact_id:
            continue
        other_start = row["char_start"] if row["char_start"] is not None else 0
        other_end = row["char_end"] if row["char_end"] is not None else 0
        if start < other_end and other_start < end:
            return row
    return None


def apply_patch(
    conn: sqlite3.Connection,
    impact_id: str,
    text: str,
    actor_id: str,
    *,
    recommendation_id: str | None = None,
) -> str:
    """Record `text` as the approved wording for `impact_id`. Returns the patch id.

    Writes one `document_patches` row and one `audit_events` row. Touches
    neither `document_chunks` nor the file on disk — see the module docstring.
    """
    patched_text = (text or "").strip()
    if not patched_text:
        raise ApiError(422, "validation_error", "Approved wording cannot be empty.")

    row = conn.execute(
        """SELECT i.id, i.document_id, i.document_chunk_id,
                  i.conflicting_start, i.conflicting_end,
                  chunk.content AS chunk_content,
                  r.id AS recommendation_id, r.current_text
             FROM impacts i
             JOIN document_chunks chunk ON chunk.id = i.document_chunk_id
             LEFT JOIN recommendations r ON r.impact_id = i.id
            WHERE i.id = ?""",
        (impact_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Impact not found.")

    content = row["chunk_content"] or ""
    start, end = resolve_span(
        content,
        start=row["conflicting_start"],
        end=row["conflicting_end"],
        fallback_text=row["current_text"],
    )
    original_text = content[start:end]

    # Re-approving the same impact (after it was reopened) replaces its own
    # earlier patch rather than stacking a second overlay on the same words.
    for existing in conn.execute(
        "SELECT id FROM document_patches WHERE impact_id = ? AND status = 'applied'",
        (impact_id,),
    ).fetchall():
        _mark_reverted(conn, existing["id"], actor_id, reason="superseded_by_new_patch")

    clash = _overlapping_patch(conn, row["document_chunk_id"], start, end, ignore_impact_id=impact_id)
    if clash is not None:
        raise ApiError(
            409,
            "conflict",
            "Another approved patch already covers this passage. Revert that one first.",
            {"conflicting_patch_id": clash["id"], "conflicting_impact_id": clash["impact_id"]},
        )

    patch_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO document_patches
             (id, document_id, document_chunk_id, impact_id, recommendation_id,
              original_text, patched_text, char_start, char_end, status, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?)""",
        (
            patch_id,
            row["document_id"],
            row["document_chunk_id"],
            impact_id,
            recommendation_id or row["recommendation_id"],
            original_text,
            patched_text,
            start,
            end,
            actor_id,
            _now(),
        ),
    )
    workflow.record_audit(
        conn,
        actor_id=actor_id,
        action="document_patch.applied",
        subject_type="document_patch",
        subject_id=patch_id,
        detail={
            "impact_id": impact_id,
            "document_id": row["document_id"],
            "document_chunk_id": row["document_chunk_id"],
            "char_start": start,
            "char_end": end,
            # The overlay is the whole mechanism, so say so in the record a
            # regulator would read.
            "document_modified": False,
        },
    )
    return patch_id


def _mark_reverted(conn: sqlite3.Connection, patch_id: str, actor_id: str, *, reason: str) -> None:
    conn.execute(
        "UPDATE document_patches SET status='reverted', reverted_by=?, reverted_at=? WHERE id=?",
        (actor_id, _now(), patch_id),
    )
    workflow.record_audit(
        conn,
        actor_id=actor_id,
        action="document_patch.reverted",
        subject_type="document_patch",
        subject_id=patch_id,
        detail={"reason": reason, "document_modified": False},
    )


def revert_patch(conn: sqlite3.Connection, patch_id: str, actor_id: str) -> sqlite3.Row:
    """Withdraw an applied patch. The row stays — the audit trail keeps both acts."""
    row = conn.execute("SELECT * FROM document_patches WHERE id = ?", (patch_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Patch not found.")
    if row["status"] != "applied":
        raise ApiError(409, "conflict", "This patch has already been reverted.")
    _mark_reverted(conn, patch_id, actor_id, reason="reverted_by_reviewer")
    return conn.execute("SELECT * FROM document_patches WHERE id = ?", (patch_id,)).fetchone()


def patch_for_impact(conn: sqlite3.Connection, impact_id: str) -> dict[str, Any] | None:
    """The applied patch for one impact, if its wording was approved."""
    row = conn.execute(
        """SELECT p.*, u.display_name AS created_by_name
             FROM document_patches p JOIN users u ON u.id = p.created_by
            WHERE p.impact_id = ? AND p.status = 'applied'
            ORDER BY p.created_at DESC LIMIT 1""",
        (impact_id,),
    ).fetchone()
    return dict(row) if row else None


def patches_for_document(
    conn: sqlite3.Connection, document_id: str, *, include_reverted: bool = False
) -> list[dict[str, Any]]:
    """Every patch on a document, ordered so the reader can apply them in place.

    One query for the whole document — the reader renders every chunk, so a
    per-chunk lookup would be an N+1 over the document's full length.
    """
    status_clause = "" if include_reverted else " AND p.status = 'applied'"
    rows = conn.execute(
        f"""SELECT p.*, u.display_name AS created_by_name, chunk.ordinal AS chunk_ordinal
              FROM document_patches p
              JOIN users u ON u.id = p.created_by
              JOIN document_chunks chunk ON chunk.id = p.document_chunk_id
             WHERE p.document_id = ?{status_clause}
             ORDER BY chunk.ordinal, p.char_start, p.created_at""",
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]
