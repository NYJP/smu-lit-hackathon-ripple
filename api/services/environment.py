"""Reset and load the local Ripple environment."""
from __future__ import annotations

import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api import db
from api.services import impact, parsing, storage

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


def _seed_requirement(conn: sqlite3.Connection, regulation_id: str, public_ref: str, subject: str, text: str, requirement_type: str, value: str | None = None, value_numeric: float | None = None, value_unit: str | None = None, source_section: str | None = None) -> tuple[str, str]:
    lineage_id, requirement_id = uuid.uuid4().hex, uuid.uuid4().hex
    now = _now()
    conn.execute("INSERT INTO requirement_lineages (id,public_ref,subject,origin_regulation_id,current_version_id,created_at) VALUES (?,?,?,?,?,?)", (lineage_id, public_ref, subject, regulation_id, requirement_id, now))
    conn.execute("INSERT INTO regulatory_requirements (id,lineage_id,regulation_id,version,requirement_text,verbatim_text,requirement_type,subject,value,value_numeric,value_unit,comparator,source_section,origin,is_current,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'extracted',1,?)", (requirement_id, lineage_id, regulation_id, 1, text, text, requirement_type, subject, value, value_numeric, value_unit, "eq" if value else None, source_section, now))
    conn.execute("INSERT INTO fts_requirements (requirement_id,requirement_text,verbatim_text) VALUES (?,?,?)", (requirement_id, text, text))
    return lineage_id, requirement_id


def _seed_analysis(conn: sqlite3.Connection, primary_id: str, amendment_id: str) -> None:
    retention_lineage, retention_v1 = _seed_requirement(conn, primary_id, "REQ-001", "customer_record_retention", "Customer records must be retained for 5 years after the relationship ends.", "duration", "5 years", 5, "years", "Section 4")
    access_lineage, _ = _seed_requirement(conn, primary_id, "REQ-002", "data_access_restriction", "Access to personal data must be limited to authorised personnel.", "obligation", source_section="Section 6")
    breach_lineage, _ = _seed_requirement(conn, primary_id, "REQ-003", "breach_notification", "Material personal-data breaches must be escalated promptly.", "notification", source_section="Section 8")
    now = _now()
    retention_v2 = uuid.uuid4().hex
    conn.execute("INSERT INTO regulatory_requirements (id,lineage_id,regulation_id,version,requirement_text,verbatim_text,requirement_type,subject,value,value_numeric,value_unit,comparator,source_section,origin,is_current,created_at) VALUES (?,?,?,2,?,?,?,?,?,?,?,'eq','Section 4','extracted',1,?)", (retention_v2, retention_lineage, amendment_id, "Customer records must be retained for 7 years after the relationship ends.", "Customer records must be retained for 7 years after the relationship ends.", "duration", "customer_record_retention", "7 years", 7, "years", now))
    conn.execute("UPDATE regulatory_requirements SET is_current=0, superseded_by=? WHERE id=?", (retention_v2, retention_v1))
    conn.execute("UPDATE requirement_lineages SET current_version_id=? WHERE id=?", (retention_v2, retention_lineage))
    conn.execute("INSERT INTO fts_requirements (requirement_id,requirement_text,verbatim_text) VALUES (?,?,?)", (retention_v2, "Customer records must be retained for 7 years after the relationship ends.", "Customer records must be retained for 7 years after the relationship ends."))
    change_id = uuid.uuid4().hex
    conn.execute("INSERT INTO regulatory_changes (id,lineage_id,source,detected_from_regulation_id,previous_requirement_id,new_requirement_id,change_type,old_value,new_value,summary,source_section,analysis_status,created_at) VALUES (?,?, 'amendment',?,?,?,?,?,?,?,'Section 4','pending',?)", (change_id, retention_lineage, amendment_id, retention_v1, retention_v2, "duration", "5 years", "7 years", "Customer Record Retention: 5 years → 7 years", now))
    lineages = [retention_lineage, access_lineage, breach_lineage]
    chunks = conn.execute("SELECT c.*, d.name FROM document_chunks c JOIN documents d ON d.id=c.document_id").fetchall()
    for chunk in chunks:
        matched: set[str] = set()
        content = chunk["content"].casefold()
        if "5 years" in content:
            matched.add(retention_lineage)
        if "applicable data protection law" in content:
            matched.add(access_lineage)
        if "breach" in content:
            matched.add(breach_lineage)
        for lineage_id in matched:
            conn.execute("INSERT INTO dependencies (id,lineage_id,document_chunk_id,document_id,relationship_type,confidence,rationale,evidence_span,evidence_start,evidence_end,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, lineage_id, chunk["id"], chunk["document_id"], "restates" if lineage_id == retention_lineage else "implements", 0.96, "Bundled sample relationship", "5 years" if lineage_id == retention_lineage else None, content.find("5 years") if lineage_id == retention_lineage else None, content.find("5 years") + 7 if lineage_id == retention_lineage else None, now))
        for lineage_id in lineages:
            conn.execute("INSERT INTO mapping_passes (document_id,lineage_id,direction,dependency_found,candidates_seen,mapped_at) VALUES (?,?,'document_first',?,?,?) ON CONFLICT(document_id,lineage_id) DO UPDATE SET dependency_found=MAX(mapping_passes.dependency_found,excluded.dependency_found), candidates_seen=mapping_passes.candidates_seen+1, mapped_at=excluded.mapped_at", (chunk["document_id"], lineage_id, int(lineage_id in matched), 1, now))
    impact.analyse_change(conn, change_id)


def load_sample(conn: sqlite3.Connection) -> dict[str, int]:
    reset(conn)
    documents_dir = SAMPLE_ROOT / "documents"
    regulations_dir = SAMPLE_ROOT / "regulations"
    primary = regulations_dir / "Personal Data Retention Regulation 2024.pdf"
    primary_id = _load_regulation(conn, primary)
    regulation_count = 1
    amendment_id = None
    for source in sorted(regulations_dir.iterdir()):
        if source != primary:
            amendment_id = _load_regulation(conn, source, primary_id)
            regulation_count += 1
    document_count = 0
    for source in sorted(documents_dir.iterdir()):
        if source.is_file():
            _load_document(conn, source)
            document_count += 1
    if amendment_id:
        _seed_analysis(conn, primary_id, amendment_id)
    conn.commit()
    return {"documents": document_count, "regulations": regulation_count}
