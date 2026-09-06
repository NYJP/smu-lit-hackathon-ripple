"""Phase 6 simulation jobs and patch-overlay invariants."""
from __future__ import annotations

import hashlib
import json

from api.services import impact
from tests.conftest import login_as
from tests.test_workflow import build_impact


def _setup(client, conn, users):
    priya = users["Priya Menon"]
    login_as(client, priya["id"])
    ids = build_impact(conn, priya["id"])
    conn.execute(
        "UPDATE regulatory_requirements SET value='5 years', value_numeric=5, value_unit='years' WHERE id=?",
        (ids["requirement"],),
    )
    conn.commit()
    response = client.post("/api/v1/simulations", json={
        "name": "Retention consultation",
        "edits": [{"lineage_id": ids["lineage"], "op": "modify", "proposed_value": "7 years", "proposed_value_numeric": 7}],
    })
    assert response.status_code == 201, response.text
    return ids, response.json()["simulation_id"]


def _rows_bytes(conn, table: str, columns: str = "*") -> bytes:
    rows = conn.execute(f"SELECT {columns} FROM {table} ORDER BY rowid").fetchall()
    return json.dumps([tuple(row) for row in rows], default=str, separators=(",", ":")).encode()


def test_run_returns_real_job_and_completes_with_named_progress(client, conn, users):
    ids, simulation_id = _setup(client, conn, users)
    before = _rows_bytes(conn, "regulatory_requirements")
    response = client.post(f"/api/v1/simulations/{simulation_id}/run")
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert isinstance(job_id, str) and job_id
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["job_type"] == "simulation_run"
    assert job["status"] == "succeeded", job
    assert job["step"] == "completed"
    assert job["progress"] == 1
    assert job["result"]["simulation_id"] == simulation_id
    assert conn.execute("SELECT status FROM simulations WHERE id=?", (simulation_id,)).fetchone()[0] == "complete"
    assert _rows_bytes(conn, "regulatory_requirements") == before
    assert conn.execute("SELECT COUNT(*) FROM impacts i JOIN regulatory_changes c ON c.id=i.regulatory_change_id WHERE c.simulation_id=?", (simulation_id,)).fetchone()[0] == 1


def test_requirement_simulate_uses_same_real_job_without_mutation(client, conn, users):
    ids, _ = _setup(client, conn, users)
    before = _rows_bytes(conn, "regulatory_requirements")
    response = client.post(f"/api/v1/requirements/{ids['lineage']}/simulate", json={"value": "7 years", "value_numeric": 7})
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    shortcut_job = client.get(f"/api/v1/jobs/{body['job_id']}").json()
    assert shortcut_job["status"] == "succeeded", shortcut_job
    assert _rows_bytes(conn, "regulatory_requirements") == before


def test_failed_execution_marks_job_and_simulation_failed(client, conn, users, monkeypatch):
    _, simulation_id = _setup(client, conn, users)
    monkeypatch.setattr(impact, "analyse_change", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("model unavailable")))
    response = client.post(f"/api/v1/simulations/{simulation_id}/run")
    job = client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "failed"
    assert job["step"] == "failed"
    assert "model unavailable" in job["error_message"]
    assert conn.execute("SELECT status FROM simulations WHERE id=?", (simulation_id,)).fetchone()[0] == "failed"


def test_estimate_reports_truthful_cache_hits(client, conn, users):
    _, simulation_id = _setup(client, conn, users)
    first = client.post(f"/api/v1/simulations/{simulation_id}/estimate").json()
    assert first == {"dependency_count": 1, "cached_count": 0, "estimated_cost_usd": 0.0002}
    client.post(f"/api/v1/simulations/{simulation_id}/run")
    second = client.post(f"/api/v1/simulations/{simulation_id}/estimate").json()
    assert second == {"dependency_count": 1, "cached_count": 1, "estimated_cost_usd": 0.0}


def test_discard_removes_only_simulation_artifacts(client, conn, users, tmp_path):
    ids, simulation_id = _setup(client, conn, users)
    source = tmp_path / "documents" / f"{ids['document']}.pdf"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(b"unchanged uploaded source")
    conn.execute("UPDATE documents SET file_path=? WHERE id=?", (f"documents/{ids['document']}.pdf", ids["document"]))
    conn.commit()
    before = {
        "requirements": _rows_bytes(conn, "regulatory_requirements"),
        "chunks": _rows_bytes(conn, "document_chunks", "id, content"),
        "file": hashlib.sha256(source.read_bytes()).hexdigest(),
        "dependencies": _rows_bytes(conn, "dependencies"),
    }
    client.post(f"/api/v1/simulations/{simulation_id}/run")
    response = client.delete(f"/api/v1/simulations/{simulation_id}")
    assert response.status_code == 204
    assert conn.execute("SELECT COUNT(*) FROM regulatory_changes WHERE simulation_id=?", (simulation_id,)).fetchone()[0] == 0
    assert _rows_bytes(conn, "regulatory_requirements") == before["requirements"]
    assert _rows_bytes(conn, "document_chunks", "id, content") == before["chunks"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before["file"]
    assert _rows_bytes(conn, "dependencies") == before["dependencies"]
