"""Reset and load the local Ripple environment."""
from __future__ import annotations

import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api import db
from api.services import parsing, storage

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample-environment"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clear_runtime_files() -> None:
    runtime_root = db.data_dir().resolve()
    for kind in ("documents", "regulations"):
        target = (runtime_root / "files" / kind).resolve()
        if runtime_root not in target.parents:
            raise RuntimeError("Refusing to clear files outside the Ripple data directory.")
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)


def reset(conn: sqlite3.Connection) -> None:
    """Clear all mutable records while retaining schema and organisation."""
    with conn:
        conn.execute("DELETE FROM vec_chunks")
        conn.execute("DELETE FROM vec_requirements")
        conn.execute("DELETE FROM fts_chunks")
        conn.execute("DELETE FROM fts_requirements")
        conn.execute("DELETE FROM simulations")
        conn.execute("DELETE FROM regulatory_changes")
        conn.execute("DELETE FROM scans")
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM documents")
        conn.execute("DELETE FROM regulations")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
    _clear_runtime_files()
    db.ensure_seed_users(conn)


def _owner(conn: sqlite3.Connection, name: str) -> str:
    return conn.execute("SELECT id FROM users WHERE display_name = ?", (name,)).fetchone()["id"]


def _document_settings(name: str) -> tuple[str, str]:
    if name == "Employee Handbook.pdf": return "Sam Rahim", "training"
    if name in {"Customer Data SOP.docx", "DPA Template.docx"}: return "Alex Tan", "sop" if "SOP" in name else "template"
    return "Priya Menon", "playbook" if "Playbook" in name else "policy"


def _load_document(conn: sqlite3.Connection, source: Path) -> str:
    owner_name, doc_type = _document_settings(source.name)
    relative_path, mime_type = storage.save_upload("documents", source.name, source.read_bytes())
    document_id = uuid.uuid4().hex
    result = parsing.parse_and_chunk_document(storage.absolute_path(relative_path), mime_type)
    now = _now()
    conn.execute("INSERT INTO documents (id,owner_id,name,doc_type,file_path,file_name,mime_type,page_count,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'ready',?)", (document_id, _owner(conn, owner_name), source.stem, doc_type, relative_path, source.name, mime_type, result.page_count, now))
    for chunk in result.chunks:
        chunk_id = uuid.uuid4().hex
        conn.execute("INSERT INTO document_chunks (id,document_id,ordinal,content,section_path,section_title,page_number,char_start,char_end,chunk_type,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (chunk_id, document_id, chunk.ordinal, chunk.content, chunk.section_path, chunk.section_title, chunk.page_number, chunk.char_start, chunk.char_end, chunk.chunk_type, now))
        conn.execute("INSERT INTO fts_chunks (chunk_id,content,section_path) VALUES (?,?,?)", (chunk_id, chunk.content, chunk.section_path or ""))
    if source.name == "Customer Data SOP.docx":
        conn.execute("INSERT INTO document_collaborators (document_id,user_id,access,added_by,added_at) VALUES (?,?, 'reviewer', ?,?)", (document_id, _owner(conn, "Priya Menon"), _owner(conn, "Alex Tan"), now))
    return document_id


def _load_regulation(conn: sqlite3.Connection, source: Path, primary_id: str | None = None) -> str:
    relative_path, _ = storage.save_upload("regulations", source.name, source.read_bytes())
    regulation_id = uuid.uuid4().hex
    parsed = parsing.parse_regulation_pdf(storage.absolute_path(relative_path))
    is_amendment = "Amendment" in source.name
    conn.execute("INSERT INTO regulations (id,title,short_name,document_kind,amends_regulation_id,file_path,file_name,page_count,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'ready',?)", (regulation_id, source.stem, "PDRR", "amendment" if is_amendment else "primary", primary_id if is_amendment else None, relative_path, source.name, parsed.page_count, _now()))
    return regulation_id


def load_sample(conn: sqlite3.Connection) -> dict[str, int]:
    reset(conn)
    documents_dir = SAMPLE_ROOT / "documents"
    regulations_dir = SAMPLE_ROOT / "regulations"
    primary = regulations_dir / "Personal Data Retention Regulation 2024.pdf"
    primary_id = _load_regulation(conn, primary)
    regulation_count = 1
    for source in sorted(regulations_dir.iterdir()):
        if source != primary:
            _load_regulation(conn, source, primary_id)
            regulation_count += 1
    document_count = 0
    for source in sorted(documents_dir.iterdir()):
        if source.is_file():
            _load_document(conn, source)
            document_count += 1
    conn.commit()
    return {"documents": document_count, "regulations": regulation_count}
