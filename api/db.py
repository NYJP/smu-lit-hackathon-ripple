"""Connection factory, sqlite-vec loading, and the migrations runner.

PRD references: section 5.1 (SQLite, sqlite-vec, FTS5), section 5.2 (boot
sequence), section 5.5 (three seeded accounts), section 6 (schema).

This module is deliberately the only place that opens a raw sqlite3
connection. Everything else goes through `get_connection()` so that WAL mode,
`foreign_keys = ON`, and the sqlite-vec extension are guaranteed to be in
effect everywhere.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import sqlite_vec

from api.sqlite_driver import sqlite3

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# The three accounts every install boots with (section 5.5). Order matters
# only for display; roles do not.
SEED_USERS = [
    ("Priya Menon", "admin"),
    ("Alex Tan", "admin"),
    ("Sam Rahim", "admin"),
]

EMBEDDING_DIMS = 1536  # text-embedding-3-small; see section 6.1.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def data_dir() -> Path:
    return Path(os.environ.get("RIPPLE_DATA_DIR", "./data")).resolve()


def db_path() -> Path:
    return data_dir() / "ripple.db"


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into an open connection.

    The driver is selected by api.sqlite_driver. Linux uses pysqlite3's
    statically linked SQLite build because some hosted Python runtimes omit
    loadable-extension support; local platforms use the standard library.
    If loading still fails, boot must fail loudly rather than silently
    degrading to keyword-only search.
    """
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    """Open a new connection with WAL mode, foreign keys, and sqlite-vec.

    A fresh connection is returned on every call rather than a shared
    singleton — FastAPI's request lifecycle and BackgroundTasks jobs each
    get their own, and sqlite3 connections are not safe to share across
    threads without care.
    """
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _load_sqlite_vec(conn)
    return conn


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply every migrations/*.sql file in order.

    Each migration is executed exactly once. Applied migration filenames are
    recorded in `_migrations` so later files may safely use ALTER TABLE while
    `/health` and diagnostics can confirm what has run.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
          filename    TEXT PRIMARY KEY,
          applied_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()

    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        already = conn.execute(
            "SELECT 1 FROM _migrations WHERE filename = ?", (path.name,)
        ).fetchone()
        if already:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO _migrations (filename, applied_at) VALUES (?, ?)",
            (path.name, _now()),
        )
        applied.append(path.name)
    conn.commit()
    return applied


def ensure_organization(conn: sqlite3.Connection) -> None:
    """Insert the single organizations row if absent (section 6)."""
    row = conn.execute("SELECT 1 FROM organizations LIMIT 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (?, ?, ?)",
            (uuid.uuid4().hex, "Ripple", _now()),
        )
        conn.commit()


def ensure_seed_users(conn: sqlite3.Connection) -> None:
    """First-boot insert of the three default accounts (section 5.5).

    Only fires when `users` is empty, so renaming or deleting-with-reassign
    later never re-seeds.
    """
    # Normalize legacy and hand-created rows on every boot. Owner and
    # collaborator records remain attribution metadata, not access control.
    conn.execute("UPDATE users SET role = 'admin' WHERE role <> 'admin'")
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count == 0:
        now = _now()
        conn.executemany(
            "INSERT INTO users (id, display_name, role, created_at) VALUES (?, ?, ?, ?)",
            [(uuid.uuid4().hex, name, role, now) for name, role in SEED_USERS],
        )
    conn.commit()


_COMPLETION_SCHEMA: dict[str, set[str]] = {
    "users": {"organization_id"},
    "documents": {"organization_id"},
    "regulations": {"organization_id"},
    "scans": {"organization_id"},
    "simulations": {"organization_id"},
    "mapping_passes": {"basis_hash", "materially_checked_at"},
    "jobs": {
        "initiated_by", "prompt_tokens", "completion_tokens",
        "estimated_cost_usd", "retry_of_job_id", "input_json",
        "stage_counters", "retryable",
    },
    "impact_cache": set(),
    "simulation_requirement_snapshots": set(),
    "dependency_events": set(),
    "recommendation_decisions": set(),
    "impact_review_events": set(),
    "document_contributions": set(),
}


def completion_schema_status(conn: sqlite3.Connection) -> dict[str, object]:
    """Return an actionable health summary for the completion schema."""
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    for table, required_columns in _COMPLETION_SCHEMA.items():
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists is None:
            missing_tables.append(table)
            continue
        actual_columns = {
            row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        absent = sorted(required_columns - actual_columns)
        if absent:
            missing_columns[table] = absent
    return {
        "status": "ok" if not missing_tables and not missing_columns else "error",
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
    }


def check_embedding_dims(configured_model_dims: int = EMBEDDING_DIMS) -> None:
    """Assert the configured embedding dimensionality matches the vec0 schema.

    Section 6.1: "If the configured embedding model's dimensionality does
    not match the vec0 declaration, the API MUST fail at boot with an
    instruction to run scripts/reindex.py --dims N." The MVP hard-codes
    text-embedding-3-small (1536 dims) as the only supported model this
    wave, so this is a static assertion rather than a live API probe (no
    OpenAI calls are made in this wave).
    """
    if configured_model_dims != EMBEDDING_DIMS:
        raise RuntimeError(
            f"Embedding dimensionality mismatch: configured model produces "
            f"{configured_model_dims} dims but vec_chunks/vec_requirements "
            f"are declared FLOAT[{EMBEDDING_DIMS}]. Run "
            f"'python scripts/reindex.py --dims {configured_model_dims}' "
            f"to rebuild the vector tables at the new dimensionality."
        )


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, closed afterwards."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def bootstrap(path: Path | None = None) -> sqlite3.Connection:
    """Full boot sequence: create ./data, migrate, load sqlite-vec, seed.

    Mirrors section 5.2 exactly (minus the OPENAI_API_KEY check and the
    OpenAI-dims probe, which live in main.py since they are HTTP/startup
    concerns, not storage concerns).
    """
    conn = get_connection(path)
    run_migrations(conn)
    check_embedding_dims()
    ensure_organization(conn)
    ensure_seed_users(conn)
    return conn
