"""Original-upload streaming (PRD sections 5.1 and 9.4)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import storage

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{kind}/{file_id}")
def get_file(
    kind: str,
    file_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    if kind == "regulations":
        row = conn.execute("SELECT file_path, file_name FROM regulations WHERE id = ?", (file_id,)).fetchone()
        media_type = "application/pdf"
    elif kind == "documents":
        access.require_visible_document(conn, user, file_id)
        row = conn.execute("SELECT file_path, file_name, mime_type FROM documents WHERE id = ?", (file_id,)).fetchone()
        media_type = row["mime_type"] if row is not None else None
    else:
        raise ApiError(404, "not_found", "File not found.")
    if row is None:
        raise ApiError(404, "not_found", "File not found.")
    path = storage.absolute_path(row["file_path"])
    if not path.is_file():
        raise ApiError(404, "not_found", "File not found.")
    return FileResponse(path, media_type=media_type, filename=row["file_name"])
