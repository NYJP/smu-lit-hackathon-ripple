"""Shared fixtures: a fresh temp database per test, wired through the real
FastAPI app (so /health, migrations, and seeding all run for real — no
mocking of the boot sequence), plus small helpers for inserting document /
collaborator rows directly, since the document endpoints are 501 stubs this
wave and PRD section 14 criteria 37-40 need real rows to scope against.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from openai.types import CreateEmbeddingResponse
from openai.types.chat import ChatCompletion

from api import db as db_module
from api.main import app

# The fake OpenAI seam. api/services/openai.py talks to the official SDK
# (`_client().chat.completions.create` / `.embeddings.create`), so tests
# patch `_client` rather than any HTTP helper. Test-supplied fakes still
# speak the older, flatter `(url, payload, headers) -> dict` contract —
# it is the readable way to express "this is what the service replied" —
# and the adapters below lift those dicts into real SDK response models,
# so a fake that drifts from the wire shape fails here rather than
# silently passing.

PostJson = Callable[[str, dict, dict], dict]


def _as_chat_completion(raw: dict, payload: dict) -> ChatCompletion:
    choices = []
    for index, choice in enumerate(raw.get("choices", [])):
        message = dict(choice.get("message", {}))
        message.setdefault("role", "assistant")
        choices.append(
            {
                "index": choice.get("index", index),
                "finish_reason": choice.get("finish_reason", "stop"),
                "message": message,
            }
        )
    return ChatCompletion.model_validate(
        {
            "id": raw.get("id", "chatcmpl-test"),
            "object": "chat.completion",
            "created": raw.get("created", 0),
            "model": raw.get("model", payload.get("model", "gpt-5")),
            "choices": choices,
            "usage": raw.get("usage"),
        }
    )


def _as_embedding_response(raw: dict, payload: dict) -> CreateEmbeddingResponse:
    data = [
        {"object": "embedding", "index": row["index"], "embedding": row["embedding"]}
        for row in raw.get("data", [])
    ]
    usage = raw.get("usage") or {"prompt_tokens": 0, "total_tokens": 0}
    usage = {"prompt_tokens": usage.get("prompt_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}
    return CreateEmbeddingResponse.model_validate(
        {
            "object": "list",
            "data": data,
            "model": raw.get("model", payload.get("model", "text-embedding-3-small")),
            "usage": usage,
        }
    )


class _FakeCompletions:
    def __init__(self, post: PostJson) -> None:
        self._post = post

    def create(self, **payload: Any) -> ChatCompletion:
        return _as_chat_completion(self._post("/chat/completions", payload, {}), payload)


class _FakeEmbeddings:
    def __init__(self, post: PostJson) -> None:
        self._post = post

    def create(self, **payload: Any) -> CreateEmbeddingResponse:
        return _as_embedding_response(self._post("/embeddings", payload, {}), payload)


class _FakeOpenAI:
    def __init__(self, post: PostJson) -> None:
        self.chat = type("_Chat", (), {"completions": _FakeCompletions(post)})()
        self.embeddings = _FakeEmbeddings(post)


def install_fake_openai(monkeypatch, post: PostJson) -> None:
    """Route every OpenAI SDK call through `post(url, payload, headers)`.

    Keeps the real `require_configured()` check in front of the fake, so
    tests that unset OPENAI_API_KEY still get the 503 the service owes
    them instead of a stubbed success.
    """
    from api.services import openai as openai_service

    def fake_client() -> _FakeOpenAI:
        openai_service.require_configured()
        return _FakeOpenAI(post)

    monkeypatch.setattr(openai_service, "_client", fake_client)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient whose app boots against an isolated temp database.

    Boots the real lifespan (migrations + sqlite-vec load + seeding), so
    this exercises the same path `python run.py dev` does.
    """
    monkeypatch.setenv("RIPPLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_post(url, payload, _headers):
        if url.endswith("/chat/completions"):
            return {"choices": [{"message": {"content": '{\"requirements\": []}'}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        vector = [1.0] + [0.0] * 1535
        return {"data": [{"index": index, "embedding": vector} for index, _ in enumerate(payload["input"])], "usage": {"prompt_tokens": len(payload["input"]), "total_tokens": len(payload["input"])}}

    install_fake_openai(monkeypatch, fake_post)
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
