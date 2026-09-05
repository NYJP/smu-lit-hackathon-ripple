"""The ONLY place ownership is consulted (PRD section 5.5 / section 11).

    "The service layer exposes exactly one function, visible_document_ids(user),
    returning owned ∪ tagged ∪ (all, if admin). Every query that touches
    documents, chunks, dependencies, impacts, or recommendations filters
    through it. There is no second path."

No router or service outside this module may filter a query by `owner_id`.
Every future router that touches documents (or anything hanging off a
document — chunks, dependencies, impacts, recommendations) must call
`visible_document_ids` or `is_document_visible` from here, and must resolve
"not visible" to a 404 (never a 403) so a member cannot infer the existence
of a colleague's document (acceptance criterion 37).
"""

from __future__ import annotations

import sqlite3

from fastapi import Depends

from api.auth import get_current_user
from api.errors import ApiError


def visible_document_ids(conn: sqlite3.Connection, user: sqlite3.Row) -> set[str]:
    """owned ∪ tagged ∪ (all, if admin) — the one accessor (section 5.5)."""
    if user["role"] == "admin":
        rows = conn.execute("SELECT id FROM documents").fetchall()
        return {row["id"] for row in rows}

    owned = conn.execute(
        "SELECT id FROM documents WHERE owner_id = ?", (user["id"],)
    ).fetchall()
    tagged = conn.execute(
        "SELECT document_id AS id FROM document_collaborators WHERE user_id = ?",
        (user["id"],),
    ).fetchall()
    return {row["id"] for row in owned} | {row["id"] for row in tagged}


def is_document_visible(conn: sqlite3.Connection, user: sqlite3.Row, document_id: str) -> bool:
    """Convenience wrapper for a single-document check.

    Still routes through `visible_document_ids` rather than a bespoke
    `WHERE owner_id = ?` query, so there remains exactly one accessor.
    """
    return document_id in visible_document_ids(conn, user)


def require_visible_document(conn: sqlite3.Connection, user: sqlite3.Row, document_id: str) -> None:
    """Raise the section-9-shaped 404 a hidden or nonexistent document gets.

    Deliberately indistinguishable from "does not exist" — a member must
    never learn that a colleague's document exists by the shape of the
    error (acceptance criterion 37: 404, not 403).
    """
    if not is_document_visible(conn, user, document_id):
        raise ApiError(404, "not_found", "Document not found.")


def can_write_document(conn: sqlite3.Connection, user: sqlite3.Row, document_id: str) -> bool:
    """Owner, a 'reviewer' collaborator, or an admin (section 5.5 resource matrix).

    A 'viewer' collaborator can see the document (via visible_document_ids)
    but not write to it, its impacts, or its recommendations (criterion 40).
    """
    if user["role"] == "admin":
        return True
    doc = conn.execute(
        "SELECT owner_id FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if doc is None:
        return False
    if doc["owner_id"] == user["id"]:
        return True
    collab = conn.execute(
        "SELECT access FROM document_collaborators WHERE document_id = ? AND user_id = ?",
        (document_id, user["id"]),
    ).fetchone()
    return bool(collab and collab["access"] == "reviewer")


def require_document_write(conn: sqlite3.Connection, user: sqlite3.Row, document_id: str) -> None:
    """404 if the document isn't even visible; 403 if visible but read-only."""
    require_visible_document(conn, user, document_id)
    if not can_write_document(conn, user, document_id):
        raise ApiError(403, "forbidden", "You have viewer access to this document, not reviewer.")


def require_admin(user: sqlite3.Row = Depends(get_current_user)) -> sqlite3.Row:
    """Role-check dependency: 403 for any signed-in user who isn't an admin.

    Regulations, requirement lineages/versions, and amendment-or-manual
    regulatory changes are writable by admins only (section 5.5 resource
    matrix; section 9's "Every endpoint that writes regulations,
    requirements, or amendment-sourced changes requires role='admin'").
    """
    if user["role"] != "admin":
        raise ApiError(403, "forbidden", "This action requires an admin account.")
    return user
