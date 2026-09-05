"""Uploaded-file storage on disk (PRD section 5.1 and section 11).

    "Uploaded files live on disk at ./data/files/regulations/ and
    ./data/files/documents/, named {uuid}{ext}. The API serves them back
    over GET /api/v1/files/{kind}/{id}."

    "Limits. 50 MB per file, 600 pages per PDF, 100 files per upload batch."

This module is the one place that writes an upload to disk or turns a
`{kind}/{id}` pair back into an absolute path — `api/routers/files.py`,
`documents.py`, and `regulations.py` all go through it rather than building
`data/files/...` paths themselves, the same "one accessor" discipline
`api/access.py` uses for visibility.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Literal

from api.db import data_dir
from api.errors import ApiError

Kind = Literal["regulations", "documents"]

MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per file (section 11)
MAX_BATCH_FILES = 100  # 100 files per upload batch (section 11)
MAX_PDF_PAGES = 600  # 600 pages per PDF (section 11)

# Extension -> mime type, for the file kinds section 7.1/7.3 parse.
EXTENSION_MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


def files_root(kind: Kind) -> Path:
    root = data_dir() / "files" / kind
    root.mkdir(parents=True, exist_ok=True)
    return root


def extension_of(filename: str) -> str:
    return Path(filename).suffix.lower()


def mime_type_for(filename: str) -> str:
    ext = extension_of(filename)
    mime = EXTENSION_MIME_TYPES.get(ext)
    if mime is None:
        allowed = ", ".join(sorted(EXTENSION_MIME_TYPES))
        raise ApiError(400, "bad_request", f"Unsupported file type '{ext or filename}'. Allowed: {allowed}.")
    return mime


def enforce_file_size(size_bytes: int, filename: str) -> None:
    if size_bytes > MAX_FILE_BYTES:
        raise ApiError(
            400,
            "bad_request",
            f"'{filename}' is {size_bytes / (1024 * 1024):.1f} MB, over the 50 MB per-file limit.",
        )


def enforce_batch_size(count: int) -> None:
    if count > MAX_BATCH_FILES:
        raise ApiError(400, "bad_request", f"Cannot upload {count} files at once; the limit is {MAX_BATCH_FILES}.")
    if count == 0:
        raise ApiError(400, "bad_request", "No files were provided.")


def enforce_pdf_page_count(page_count: int) -> None:
    """Reject PDFs over the documented 600-page ingestion limit."""
    if page_count > MAX_PDF_PAGES:
        raise ApiError(
            400,
            "bad_request",
            f"PDF has {page_count} pages; the limit is {MAX_PDF_PAGES}.",
        )


def save_upload(kind: Kind, filename: str, content: bytes) -> tuple[str, str]:
    """Write `content` to disk at `data/files/{kind}/{uuid}{ext}`.

    Returns (relative_path, mime_type). `relative_path` is stored in
    `regulations.file_path` / `documents.file_path` relative to
    `RIPPLE_DATA_DIR`, per the schema comment in section 6.
    """
    ext = extension_of(filename)
    mime_type = mime_type_for(filename)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    target = files_root(kind) / stored_name
    target.write_bytes(content)
    relative_path = f"files/{kind}/{stored_name}"
    return relative_path, mime_type


def absolute_path(relative_path: str) -> Path:
    return data_dir() / relative_path


def delete_file(relative_path: str | None) -> None:
    """Best-effort delete; a missing file is not an error — the row is
    still going away, and a half-cleaned-up disk must never block a delete
    the user asked for."""
    if not relative_path:
        return
    path = absolute_path(relative_path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
