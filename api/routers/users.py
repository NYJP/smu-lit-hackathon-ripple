"""GET /users, POST /users, PATCH /users/{id}, DELETE /users/{id} (section 9.9).

GET /users is the one roster-reading path exempt from the session-required
rule — "you cannot tag someone you cannot name" (section 5.5), and it is
what the /who picker renders before any session exists. Every write is
admin-only.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.access import require_admin
from api.db import get_db
from api.errors import ApiError
from api.models import UserCreate, UserOut, UserPatch, UsersListOut

router = APIRouter(prefix="/users", tags=["users"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_out(row: sqlite3.Row) -> UserOut:
    return UserOut(
        id=row["id"],
        display_name=row["display_name"],
        role=row["role"],
        document_count=row["document_count"],
        last_seen_at=row["last_seen_at"],
    )


_ROSTER_QUERY = """
    SELECT u.id, u.display_name, u.role, u.last_seen_at,
           (SELECT COUNT(*) FROM documents d WHERE d.owner_id = u.id) AS document_count
    FROM users u
    ORDER BY u.display_name COLLATE NOCASE
"""

_BY_ID_QUERY = """
    SELECT u.id, u.display_name, u.role, u.last_seen_at,
           (SELECT COUNT(*) FROM documents d WHERE d.owner_id = u.id) AS document_count
    FROM users u WHERE u.id = ?
"""


@router.get("", response_model=UsersListOut)
def list_users(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(_ROSTER_QUERY).fetchall()
    return UsersListOut(items=[_row_to_out(r) for r in rows])


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _admin: sqlite3.Row = Depends(require_admin),
):
    existing = conn.execute(
        "SELECT 1 FROM users WHERE display_name = ? COLLATE NOCASE", (payload.display_name,)
    ).fetchone()
    if existing is not None:
        raise ApiError(409, "conflict", "A user with that name already exists.")
    user_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (id, display_name, role, created_at) VALUES (?, ?, ?, ?)",
        (user_id, payload.display_name, payload.role, _now()),
    )
    conn.commit()
    row = conn.execute(_BY_ID_QUERY, (user_id,)).fetchone()
    return _row_to_out(row)


def _get_user_or_404(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, display_name, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "No such user.")
    return row


def _admin_count(conn: sqlite3.Connection, exclude_user_id: str | None = None) -> int:
    if exclude_user_id:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND id <> ?", (exclude_user_id,)
        ).fetchone()["c"]
    return conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'").fetchone()["c"]


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: str,
    payload: UserPatch,
    conn: sqlite3.Connection = Depends(get_db),
    _admin: sqlite3.Row = Depends(require_admin),
):
    target = _get_user_or_404(conn, user_id)

    if payload.role is not None and payload.role != target["role"]:
        if target["role"] == "admin" and payload.role != "admin" and _admin_count(conn, exclude_user_id=user_id) == 0:
            # Not explicit in section 9.9's PATCH row, but demoting the sole
            # admin would silently violate the same "never zero admins"
            # invariant DELETE enforces — extending the guard here is the
            # conservative reading. See report for the ambiguity note.
            raise ApiError(409, "conflict", "Cannot remove the last admin.")

    if payload.display_name is not None:
        clash = conn.execute(
            "SELECT 1 FROM users WHERE display_name = ? COLLATE NOCASE AND id <> ?",
            (payload.display_name, user_id),
        ).fetchone()
        if clash is not None:
            raise ApiError(409, "conflict", "A user with that name already exists.")
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (payload.display_name, user_id))

    if payload.role is not None:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (payload.role, user_id))

    conn.commit()
    row = conn.execute(_BY_ID_QUERY, (user_id,)).fetchone()
    return _row_to_out(row)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    reassign_to: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _admin: sqlite3.Row = Depends(require_admin),
):
    target = _get_user_or_404(conn, user_id)

    if target["role"] == "admin" and _admin_count(conn, exclude_user_id=user_id) == 0:
        raise ApiError(409, "conflict", "Cannot delete the last admin.")

    owned_count = conn.execute(
        "SELECT COUNT(*) AS c FROM documents WHERE owner_id = ?", (user_id,)
    ).fetchone()["c"]

    if owned_count > 0:
        if not reassign_to:
            raise ApiError(
                409,
                "conflict",
                f"This user owns {owned_count} document(s). Pass ?reassign_to=<user_id> to reassign them first.",
                details={"owned_document_count": owned_count},
            )
        if reassign_to == user_id:
            raise ApiError(400, "bad_request", "reassign_to must be a different user.")
        _get_user_or_404(conn, reassign_to)
        conn.execute(
            "UPDATE documents SET owner_id = ? WHERE owner_id = ?", (reassign_to, user_id)
        )

    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    return None
