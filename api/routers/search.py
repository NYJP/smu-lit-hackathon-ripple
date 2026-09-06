"""Visibility-scoped hybrid semantic and keyword search (section 7.5)."""

from __future__ import annotations

from api.sqlite_driver import sqlite3

from typing import Literal

from fastapi import APIRouter, Depends

from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import openai, retrieval

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    q: str,
    scope: Literal["chunks", "requirements", "all"] = "all",
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    if not q.strip():
        raise ApiError(422, "validation_error", "A search query is required.")
    openai.require_configured()
    return retrieval.search(conn, user, q.strip(), scope, access.visible_document_ids(conn, user))
