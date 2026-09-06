"""Session cookies and the current-user dependency. No credentials (section 5.5).

Choosing a name from the roster creates a session; there is nothing to
authenticate, so this module never hashes, checks, or rate-limits anything.
The opaque session id is the entire security model, and section 5.5 and
section 16 are explicit that it is a point-of-view selector, not a boundary.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request, Response

from api.db import get_db
from api.errors import ApiError

COOKIE_NAME = "ripple_session"
SESSION_TTL_DAYS = 30


def _secure_cookie() -> bool:
    return os.environ.get("RIPPLE_COOKIE_SECURE", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def create_session(conn: sqlite3.Connection, user_id: str) -> tuple[str, datetime]:
    """Create a session row for `user_id`. Returns (session_id, expires_at).

    The session id is 256 bits of randomness (`secrets.token_hex(32)` ==
    32 bytes == 256 bits, rendered as 64 hex characters) — opaque, unguessable,
    and carrying no information about the user it belongs to.
    """
    session_id = secrets.token_hex(32)
    now = _now()
    expires = now + timedelta(days=SESSION_TTL_DAYS)
    conn.execute(
        "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (session_id, user_id, _iso(now), _iso(expires)),
    )
    conn.execute(
        "UPDATE users SET last_seen_at = ? WHERE id = ?",
        (_iso(now), user_id),
    )
    conn.commit()
    return session_id, expires


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()


def get_session_user(conn: sqlite3.Connection, session_id: str | None) -> sqlite3.Row | None:
    """Look up the user behind a session id, honouring the 30-day expiry."""
    if not session_id:
        return None
    return conn.execute(
        """
        SELECT u.id, u.display_name, u.role, u.created_at, u.last_seen_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.id = ? AND s.expires_at > ?
        """,
        (session_id, _iso(_now())),
    ).fetchone()


def set_session_cookie(response: Response, session_id: str, expires: datetime) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(),
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        expires=_iso(expires),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", secure=_secure_cookie(), samesite="lax")


def get_current_user(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row:
    """FastAPI dependency: the session cookie's user, or a 401.

    Every endpoint except GET /users, POST /auth/session, DELETE
    /auth/session, and GET /health depends on this (section 9).
    """
    session_id = request.cookies.get(COOKIE_NAME)
    user = get_session_user(conn, session_id)
    if user is None:
        raise ApiError(401, "unauthenticated", "Sign in required — choose an account at /who.")
    return user
