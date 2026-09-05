"""Shared fixtures: a fresh temp database per test, wired through the real
FastAPI app (so /health, migrations, and seeding all run for real — no
mocking of the boot sequence), plus small helpers for inserting document /
collaborator rows directly, since the document endpoints are 501 stubs this
wave and PRD section 14 criteria 37-40 need real rows to scope against.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api import db as db_module
from api.main import app


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient whose app boots against an isolated temp database.

    Boots the real lifespan (migrations + sqlite-vec load + seeding), so
    this exercises the same path `python run.py dev` does.
    """
    monkeypatch.setenv("RIPPLE_DATA_DIR", str(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def conn(client):
    """A direct sqlite3 connection to the same temp database `client` uses.

    Used to seed document/collaborator rows straight into the schema, and
    to assert on stored state that no 501-stub endpoint can yet return.
    """
    connection = db_module.get_connection()
    yield connection
    connection.close()


@pytest.fixture()
def users(conn):
    """{display_name: row-as-dict} for the three seeded accounts."""
    rows = conn.execute("SELECT id, display_name, role FROM users").fetchall()
    return {row["display_name"]: dict(row) for row in rows}


def login_as(client: TestClient, user_id: str):
    resp = client.post("/api/v1/auth/session", json={"user_id": user_id})
    assert resp.status_code == 200, resp.text
    return resp


def make_document(conn, owner_id: str, name: str = "Test Document") -> str:
    """Insert a minimal, schema-valid `documents` row directly (bypassing
    the 501 upload endpoint) so scoping tests have something real to scope."""
    doc_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO documents (id, owner_id, name, doc_type, file_path, file_name,
                                mime_type, status, created_at)
        VALUES (?, ?, ?, 'policy', ?, ?, 'application/pdf', 'ready', ?)
        """,
        (doc_id, owner_id, name, f"documents/{doc_id}.pdf", f"{name}.pdf", _now()),
    )
    conn.commit()
    return doc_id


def add_collaborator(conn, document_id: str, user_id: str, access: str, added_by: str) -> None:
    conn.execute(
        """
        INSERT INTO document_collaborators (document_id, user_id, access, added_by, added_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (document_id, user_id, access, added_by, _now()),
    )
    conn.commit()
