"""Original-upload streaming (PRD sections 5.1 and 9.4)."""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError
from api.services import rendering, storage

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{kind}/{file_id}")
def get_file(
    kind: str,
    file_id: str,
    inline: bool = False,
    variant: Literal["original", "display"] = "original",
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(get_current_user),
):
    """Stream an upload. `variant=display` returns something the browser can
    render: for a PDF that is the original, and for a .docx or .txt it is the
    cached rendering from api/services/rendering.py. `variant=original`
    (the default, used by every download link) always returns the file the
    user uploaded, byte for byte."""
    if kind == "regulations":
        row = conn.execute("SELECT file_path, file_name FROM regulations WHERE id = ?", (file_id,)).fetchone()
        media_type = "application/pdf"
    elif kind == "documents":
        access.require_visible_document(conn, user, file_id)
        row = conn.execute("SELECT file_path, file_name, name, mime_type FROM documents WHERE id = ?", (file_id,)).fetchone()
        media_type = row["mime_type"] if row is not None else None
    else:
        raise ApiError(404, "not_found", "File not found.")
    if row is None:
        raise ApiError(404, "not_found", "File not found.")
    path = storage.absolute_path(row["file_path"])
    if not path.is_file():
        raise ApiError(404, "not_found", "File not found.")
    if kind == "documents" and variant == "display":
        try:
            path = rendering.display_pdf(row)
        except Exception:
            # A document that cannot be rendered still has a clause rail and a
            # download; a 502 here would only blank the reader.
            raise ApiError(502, "external_service_error", "This document could not be rendered for display.")
        media_type = rendering.PDF_MIME_TYPE
    # A rendered .docx must not be offered under its .docx name with a PDF
    # body; name the download after the file actually being served.
    download_name = path.name if path.name.endswith(".display.pdf") else row["file_name"]
    headers = None
    if inline and media_type == "application/pdf":
        safe_name = download_name.replace('"', "")
        headers = {"Content-Disposition": f'inline; filename="{safe_name}"'}
    return FileResponse(path, media_type=media_type, filename=download_name, headers=headers)
