"""Phase 5 graph API: filtering, truthful caps, and query discipline."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from tests.conftest import login_as
from tests.test_workflow import build_impact


def _login(client, users):
    login_as(client, users["Priya Menon"]["id"])


def test_limit_caps_nodes_and_reports_every_omission(client, conn, users):
    _login(client, users)
    for _ in range(4):
        build_impact(conn, users["Priya Menon"]["id"])
    full = client.get("/api/v1/graph?seed=all").json()
    capped = client.get("/api/v1/graph?seed=all&limit=3").json()
    assert len(capped["nodes"]) <= 3
    assert capped["truncated"]["nodes_omitted"] == len(full["nodes"]) - len(capped["nodes"])
    assert capped["truncated"]["edges_omitted"] == len(full["edges"]) - len(capped["edges"])
    full_docs = {edge["document_id"] for edge in full["edges"]}
    shown_docs = {edge["document_id"] for edge in capped["edges"]}
    assert capped["hidden_document_count"] == len(full_docs - shown_docs)


def test_severity_status_and_team_filters(client, conn, users):
    _login(client, users)
    high = build_impact(conn, users["Priya Menon"]["id"], impact_level="high", review_status="in_review")
    low = build_impact(conn, users["Alex Tan"]["id"], impact_level="low", review_status="detected")
    team_id = uuid.uuid4().hex
    conn.execute("INSERT INTO teams(id,name,created_at) VALUES (?,?,?)", (team_id, "Legal", datetime.now(timezone.utc).isoformat()))
    conn.execute("INSERT INTO document_teams(document_id,team_id,assigned_at) VALUES (?,?,?)", (high["document"], team_id, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    body = client.get(f"/api/v1/graph?severity=high&review_status=in_review&team_id={team_id}").json()
    assert {edge["id"] for edge in body["edges"]} == {high["dependency"]}
    assert low["dependency"] not in {edge["id"] for edge in body["edges"]}


def test_simulation_filter_returns_only_its_dependencies(client, conn, users):
    _login(client, users)
    simulated = build_impact(conn, users["Priya Menon"]["id"])
    build_impact(conn, users["Priya Menon"]["id"])
    simulation_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO simulations(id,created_by,name,status,created_at,updated_at) VALUES (?,?,'Test simulation','complete',?,?)", (simulation_id, users["Priya Menon"]["id"], now, now))
    conn.execute("UPDATE regulatory_changes SET source='simulation',simulation_id=? WHERE id=?", (simulation_id, simulated["change"]))
    conn.commit()
    body = client.get(f"/api/v1/graph?simulation_id={simulation_id}").json()
    assert {edge["id"] for edge in body["edges"]} == {simulated["dependency"]}
    assert body["edges"][0]["change_source"] == "simulation"


def test_graph_batches_contributor_lookup(client, conn, users, monkeypatch):
    _login(client, users)
    for _ in range(6):
        build_impact(conn, users["Priya Menon"]["id"])
    from api.services import contributions
    original = contributions.for_spans
    calls = 0
    def counted(connection, spans):
        nonlocal calls
        calls += 1
        return original(connection, spans)
    def legacy(*_args, **_kwargs):
        raise AssertionError("graph must not perform the per-edge lookup")
    monkeypatch.setattr(contributions, "for_spans", counted)
    monkeypatch.setattr(contributions, "for_span", legacy)
    response = client.get("/api/v1/graph?seed=all")
    assert response.status_code == 200
    assert calls == 1
