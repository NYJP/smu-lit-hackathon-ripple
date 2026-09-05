"""Authentication-only authorization for the local all-admin product build.

Owner and collaborator associations remain workflow metadata, but no
authenticated account is restricted by them. Existing helper names remain so
routers have one stable access boundary while the wider PRD work proceeds.
"""

from __future__ import annotations

import sqlite3

from fastapi import Depends

from api.auth import get_current_user
from api.errors import ApiError


def visible_document_ids(conn: sqlite3.Connection, user: sqlite3.Row) -> set[str]:
    """Return every document for every authenticated account."""
    del user
    rows = conn.execute("SELECT id FROM documents").fetchall()
    return {row["id"] for row in rows}


def is_document_visible(conn: sqlite3.Connection, user: sqlite3.Row, document_id: str) -> bool:
    """Check existence through the shared document accessor."""
    return document_id in visible_document_ids(conn, user)


def require_visible_document(conn: sqlite3.Connection, user: sqlite3.Row, document_id: str) -> None:
    """Raise the standard 404 for a nonexistent document."""
    if not is_document_visible(conn, user, document_id):
        raise ApiError(404, "not_found", "Document not found.")


def can_write_document(conn: sqlite3.Connection, user: sqlite3.Row, document_id: str) -> bool:
    """Every authenticated account may write every existing document."""
    del user
    return conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is not None


def require_document_write(conn: sqlite3.Connection, user: sqlite3.Row, document_id: str) -> None:
    """Require only that the target document exists."""
    require_visible_document(conn, user, document_id)


def require_admin(user: sqlite3.Row = Depends(get_current_user)) -> sqlite3.Row:
    """Compatibility dependency: every authenticated account is an admin."""
    return user
