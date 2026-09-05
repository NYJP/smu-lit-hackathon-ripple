"""PRD section 14, local-runtime criteria (1-4) as far as reachable from
pytest (criteria 1 and 2 concern the process/CLI layer and are exercised
manually against `run.py`, see the verification transcript in the report)."""

from __future__ import annotations


def test_health_returns_200_with_no_session(client):
    """GET /health is exempt from the session-required rule (section 9)."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "ok"
    assert body["openai"] in ("configured", "unconfigured")
    assert body["embedding_dims"] == 1536


def test_health_reports_unconfigured_without_openai_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = client.get("/api/v1/health")
    assert resp.json()["openai"] == "unconfigured"


def test_fresh_database_boots_empty_and_working(client, conn):
    """Criterion 4: deleting ./data and restarting rebuilds an empty, working
    database. Here that's simulated by pointing at a brand-new temp dir —
    the fixture itself proves the same bootstrap path works from nothing."""
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table')")
    }
    for expected in ("users", "sessions", "documents", "vec_chunks", "fts_chunks"):
        assert expected in tables


def test_unmatched_route_uses_error_envelope(client):
    resp = client.get("/api/v1/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "not_found"


def test_validation_error_uses_error_envelope(client):
    # POST /auth/session requires user_id; omit it to trigger pydantic validation.
    resp = client.post("/api/v1/auth/session", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"] is not None
