"""Reset and load manifest-driven local Ripple sample environments."""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite_vec

from api import db
from api.errors import ApiError
from api.services import impact, openai, parsing, storage

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample-environment"
SCENARIOS_FILE = SAMPLE_ROOT / "scenarios.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scenarios() -> dict[str, dict[str, Any]]:
    with SCENARIOS_FILE.open(encoding="utf-8") as stream:
        return json.load(stream)


def list_scenarios() -> list[dict[str, str]]:
    return [
        {"id": scenario_id, "label": item["label"], "description": item["description"]}
        for scenario_id, item in _scenarios().items()
    ]


def _scenario_files(item: dict[str, Any]) -> tuple[Path, list[Path]]:
    scenario_root = (SAMPLE_ROOT / item["root"]).resolve()
    if scenario_root != SAMPLE_ROOT.resolve() and SAMPLE_ROOT.resolve() not in scenario_root.parents:
        raise ApiError(500, "invalid_sample_scenario", "The sample scenario path is invalid.")
    relative_files = [item["primary"]["file"], item["amendment"]["file"]]
    relative_files.extend(document["file"] for document in item["documents"])
    files = [(scenario_root / relative).resolve() for relative in relative_files]
    if any(scenario_root != path and scenario_root not in path.parents for path in files):
        raise ApiError(500, "invalid_sample_scenario", "The sample scenario contains an invalid file path.")
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        raise ApiError(500, "invalid_sample_scenario", f"The sample scenario is incomplete: {', '.join(missing)}")
    return scenario_root, files


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


def _load_document(conn: sqlite3.Connection, source: Path, item: dict[str, Any]) -> str:
    relative_path, mime_type = storage.save_upload("documents", source.name, source.read_bytes())
    document_id = uuid.uuid4().hex
    result = parsing.parse_and_chunk_document(storage.absolute_path(relative_path), mime_type)
    now = _now()
    conn.execute(
        "INSERT INTO documents (id,owner_id,name,doc_type,file_path,file_name,mime_type,page_count,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'ready',?)",
        (document_id, _owner(conn, item["owner"]), source.stem, item["doc_type"], relative_path, source.name, mime_type, result.page_count, now),
    )
    owner_id = _owner(conn, item["owner"])
    for collaborator in item.get("shared_with", []):
        collaborator_id = _owner(conn, collaborator)
        if collaborator_id != owner_id:
            conn.execute(
                "INSERT INTO document_collaborators (document_id,user_id,access,added_by,added_at) VALUES (?,?,'reviewer',?,?)",
                (document_id, collaborator_id, owner_id, now),
            )
    for chunk in result.chunks:
        chunk_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO document_chunks (id,document_id,ordinal,content,section_path,section_title,page_number,char_start,char_end,chunk_type,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (chunk_id, document_id, chunk.ordinal, chunk.content, chunk.section_path, chunk.section_title, chunk.page_number, chunk.char_start, chunk.char_end, chunk.chunk_type, now),
        )
        conn.execute("INSERT INTO fts_chunks (chunk_id,content,section_path) VALUES (?,?,?)", (chunk_id, chunk.content, chunk.section_path or ""))
    return document_id


def _load_regulation(conn: sqlite3.Connection, source: Path, item: dict[str, Any], kind: str, primary_id: str | None = None) -> str:
    relative_path, _ = storage.save_upload("regulations", source.name, source.read_bytes())
    regulation_id = uuid.uuid4().hex
    parsed = parsing.parse_regulation_pdf(storage.absolute_path(relative_path))
    conn.execute(
        "INSERT INTO regulations (id,title,short_name,document_kind,amends_regulation_id,file_path,file_name,page_count,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'ready',?)",
        (regulation_id, item["title"], item["short_name"], kind, primary_id, relative_path, source.name, parsed.page_count, _now()),
    )
    return regulation_id


def _insert_requirement(conn: sqlite3.Connection, lineage_id: str, regulation_id: str, version: int, item: dict[str, Any], *, current: bool, amended: bool = False) -> str:
    requirement_id = uuid.uuid4().hex
    text = item["new_text"] if amended else item["text"]
    value = item.get("new_value") if amended else item.get("value")
    value_numeric = item.get("new_value_numeric") if amended else item.get("value_numeric")
    now = _now()
    conn.execute(
        """INSERT INTO regulatory_requirements
           (id,lineage_id,regulation_id,version,requirement_text,verbatim_text,requirement_type,subject,value,value_numeric,value_unit,comparator,source_section,origin,is_current,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'extracted',?,?)""",
        (requirement_id, lineage_id, regulation_id, version, text, text, item["requirement_type"], item["subject"], value, value_numeric, item.get("value_unit"), "eq" if value else None, item.get("source_section"), int(current), now),
    )
    conn.execute("INSERT INTO fts_requirements (requirement_id,requirement_text,verbatim_text) VALUES (?,?,?)", (requirement_id, text, text))
    return requirement_id


def _seed_requirements(conn: sqlite3.Connection, primary_id: str, amendment_id: str, items: list[dict[str, Any]]) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    seeded: list[tuple[str, dict[str, Any]]] = []
    changes: list[str] = []
    for item in items:
        lineage_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO requirement_lineages (id,public_ref,subject,origin_regulation_id,current_version_id,created_at) VALUES (?,?,?,?,NULL,?)",
            (lineage_id, item["public_ref"], item["subject"], primary_id, _now()),
        )
        first_id = _insert_requirement(conn, lineage_id, primary_id, 1, item, current="new_text" not in item)
        current_id = first_id
        if "new_text" in item:
            current_id = _insert_requirement(conn, lineage_id, amendment_id, 2, item, current=True, amended=True)
            conn.execute("UPDATE regulatory_requirements SET superseded_by=? WHERE id=?", (current_id, first_id))
        conn.execute("UPDATE requirement_lineages SET current_version_id=? WHERE id=?", (current_id, lineage_id))
        if "new_text" in item:
            change_id = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO regulatory_changes
                   (id,lineage_id,source,detected_from_regulation_id,previous_requirement_id,new_requirement_id,change_type,old_value,new_value,summary,source_section,analysis_status,created_at)
                   VALUES (?,?, 'amendment',?,?,?,?,?,?,?,?,'pending',?)""",
                (change_id, lineage_id, amendment_id, first_id, current_id, item["change_type"], item.get("value"), item.get("new_value"), item["change_summary"], item.get("source_section"), _now()),
            )
            changes.append(change_id)
        seeded.append((lineage_id, item))
    return seeded, changes


def _seed_dependencies(conn: sqlite3.Connection, seeded: list[tuple[str, dict[str, Any]]]) -> int:
    documents = conn.execute("SELECT id FROM documents").fetchall()
    created = 0
    now = _now()
    for document in documents:
        chunks = conn.execute("SELECT * FROM document_chunks WHERE document_id=? ORDER BY ordinal", (document["id"],)).fetchall()
        for lineage_id, item in seeded:
            match = None
            for chunk in chunks:
                folded = chunk["content"].casefold()
                for phrase in item.get("match_phrases", []):
                    start = folded.find(phrase.casefold())
                    if start >= 0:
                        match = (chunk, start, start + len(phrase))
                        break
                if match:
                    break
            if match:
                chunk, start, end = match
                conn.execute(
                    """INSERT INTO dependencies
                       (id,lineage_id,document_chunk_id,document_id,relationship_type,confidence,rationale,evidence_span,evidence_start,evidence_end,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (uuid.uuid4().hex, lineage_id, chunk["id"], document["id"], "restates" if "new_text" in item else "implements", 0.96, "Bundled sample relationship", chunk["content"][start:end], start, end, now),
                )
                created += 1
            conn.execute(
                "INSERT INTO mapping_passes (document_id,lineage_id,direction,dependency_found,candidates_seen,mapped_at) VALUES (?,?,'document_first',?,?,?)",
                (document["id"], lineage_id, int(match is not None), len(chunks), now),
            )
    return created


def _embed_environment(conn: sqlite3.Connection) -> tuple[int, dict[str, Any]]:
    chunks = conn.execute(
        "SELECT id, content, section_path, chunk_type FROM document_chunks ORDER BY id"
    ).fetchall()
    eligible_chunks = [
        row for row in chunks
        if row["chunk_type"] != "heading" and len(" ".join(row["content"].split())) >= 60
    ]
    requirements = conn.execute("SELECT id,requirement_text FROM regulatory_requirements ORDER BY id").fetchall()
    texts = [
        f"{(row['section_path'] or '').strip()}\n{row['content'].strip()}" for row in eligible_chunks
    ] + [row["requirement_text"] for row in requirements]
    try:
        embedding = openai.embed(texts)
    except openai.ExternalServiceError as exc:
        raise ApiError(502, "embedding_failed", str(exc)) from exc
    chunk_vectors = embedding.value[:len(eligible_chunks)]
    requirement_vectors = embedding.value[len(eligible_chunks):]
    for row, vector in zip(eligible_chunks, chunk_vectors, strict=True):
        conn.execute("INSERT INTO vec_chunks (chunk_id,embedding) VALUES (?,?)", (row["id"], sqlite_vec.serialize_float32(vector)))
    for row, vector in zip(requirements, requirement_vectors, strict=True):
        conn.execute("INSERT INTO vec_requirements (requirement_id,embedding) VALUES (?,?)", (row["id"], sqlite_vec.serialize_float32(vector)))
    return len(embedding.value), embedding.usage.as_dict()


def load_sample(conn: sqlite3.Connection, scenario_id: str = "pdpf") -> dict[str, Any]:
    scenarios = _scenarios()
    item = scenarios.get(scenario_id)
    if item is None:
        raise ApiError(422, "validation_error", "Unknown sample scenario.")
    scenario_root, _ = _scenario_files(item)
    openai.require_configured()
    reset(conn)
    primary = item["primary"]
    amendment = item["amendment"]
    primary_id = _load_regulation(conn, scenario_root / primary["file"], primary, "primary")
    amendment_id = _load_regulation(conn, scenario_root / amendment["file"], amendment, "amendment", primary_id)
    for document in item["documents"]:
        _load_document(conn, scenario_root / document["file"], document)
    seeded, changes = _seed_requirements(conn, primary_id, amendment_id, item["requirements"])
    embedding_count, embedding_usage = _embed_environment(conn)
    dependency_count = _seed_dependencies(conn, seeded)
    impact_count = sum(
        impact.analyse_change(conn, change_id).impacts_created for change_id in changes
    )
    expected_embeddings = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM document_chunks
              WHERE chunk_type <> 'heading' AND length(trim(content)) >= 60)
             + (SELECT COUNT(*) FROM regulatory_requirements) AS n"""
    ).fetchone()["n"]
    checks = {
        "documents": conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == len(item["documents"]),
        "regulations": conn.execute("SELECT COUNT(*) AS n FROM regulations").fetchone()["n"] == 2,
        "requirements": conn.execute("SELECT COUNT(*) AS n FROM regulatory_requirements WHERE is_current=1").fetchone()["n"] == len(item["requirements"]),
        "dependencies": conn.execute("SELECT COUNT(DISTINCT lineage_id) AS n FROM dependencies").fetchone()["n"] == len(item["requirements"]),
        "impacts": impact_count >= len(changes),
        "embeddings": embedding_count == expected_embeddings,
    }
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise ApiError(500, "sample_verification_failed", f"Scenario verification failed: {failed}.")
    conn.commit()
    return {
        "scenario_id": scenario_id,
        "scenario": item["label"],
        "documents": len(item["documents"]),
        "regulations": 2,
        "requirements": len(item["requirements"]),
        "dependencies": dependency_count,
        "impacts": impact_count,
        "embeddings": embedding_count,
        "embedding_usage": embedding_usage,
    }
