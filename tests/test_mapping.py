"""Dependency mapping: persisted evidence, negative passes, and scoped reads."""

from __future__ import annotations

import sqlite_vec

from api.services import mapping
from tests.conftest import login_as, make_document


_VECTOR = [1.0] + [0.0] * 1535


def _seed_requirement(conn) -> str:
    conn.execute("INSERT INTO regulations (id, title, document_kind, file_path, file_name, status, created_at) VALUES ('map-reg', 'Retention Rules', 'primary', 'regulations/r.pdf', 'r.pdf', 'ready', '2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO requirement_lineages (id, public_ref, subject, origin_regulation_id, created_at) VALUES ('map-lineage', 'REQ-001', 'record_retention', 'map-reg', '2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO regulatory_requirements (id, lineage_id, regulation_id, requirement_text, requirement_type, subject, value, is_current, created_at) VALUES ('map-requirement', 'map-lineage', 'map-reg', 'Customer records must be retained for 30 g.', 'threshold', 'record_retention', '30 g', 1, '2026-01-01T00:00:00+00:00')")
    conn.execute("UPDATE requirement_lineages SET current_version_id = 'map-requirement' WHERE id = 'map-lineage'")
    conn.execute("INSERT INTO fts_requirements (requirement_id, requirement_text, verbatim_text) VALUES ('map-requirement', 'Customer records must be retained for 30 g.', '')")
    conn.execute("INSERT INTO vec_requirements (requirement_id, embedding) VALUES ('map-requirement', ?)", (sqlite_vec.serialize_float32(_VECTOR),))
    conn.commit()
    return "map-lineage"


def _add_chunk(conn, document_id: str, chunk_id: str, content: str) -> None:
    conn.execute("INSERT INTO document_chunks (id, document_id, ordinal, content, chunk_type, created_at) VALUES (?, ?, 0, ?, 'paragraph', '2026-01-01T00:00:00+00:00')", (chunk_id, document_id, content))
    conn.execute("INSERT INTO fts_chunks (chunk_id, content, section_path) VALUES (?, ?, '')", (chunk_id, content))
    conn.execute("INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)", (chunk_id, sqlite_vec.serialize_float32(_VECTOR)))
    conn.commit()


def _mapping_response(monkeypatch, *, span: str | None) -> None:
    from api.services import openai

    def fake_structured(_system, _user, _schema, **_kwargs):
        return {
            "decisions": [{
                "chunk_id": "map-chunk", "depends": span is not None,
                "relationship_type": "restates" if span else None,
                "confidence": 0.91 if span else 0.0,
                "rationale": "Exact threshold." if span else "Vocabulary only.",
                "evidence_span": span,
            }]
        }, openai.Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5)

    monkeypatch.setattr(openai, "structured_completion", fake_structured)


def test_document_mapping_persists_exact_evidence_and_is_idempotent(client, conn, users, monkeypatch):
    """Removing evidence resolution or upsert logic loses provenance or duplicates a rerun."""
    lineage_id = _seed_requirement(conn)
    document_id = make_document(conn, users["Alex Tan"]["id"])
    content = "Customer records must be retained for 30 g under the policy."
    _add_chunk(conn, document_id, "map-chunk", content)
    _mapping_response(monkeypatch, span="retained for 30 g")

    first = mapping.map_document(conn, document_id)
    second = mapping.map_document(conn, document_id)

    dependency = conn.execute("SELECT evidence_span, evidence_start, evidence_end, relationship_type, confidence FROM dependencies").fetchone()
    assert first.dependencies_added == 1
    assert second.dependencies_added == 0
    assert dict(dependency) == {
        "evidence_span": "retained for 30 g", "evidence_start": content.index("retained for 30 g"),
        "evidence_end": content.index("retained for 30 g") + len("retained for 30 g"),
        "relationship_type": "restates", "confidence": 0.91,
    }
    assert conn.execute("SELECT COUNT(*) AS count FROM dependencies").fetchone()["count"] == 1
    mapping_pass = conn.execute("SELECT direction, dependency_found, candidates_seen FROM mapping_passes WHERE document_id = ? AND lineage_id = ?", (document_id, lineage_id)).fetchone()
    assert dict(mapping_pass) == {"direction": "document_first", "dependency_found": 1, "candidates_seen": 1}


def test_document_mapping_records_negative_pass_and_coverage(client, conn, users, monkeypatch):
    """Removing no-match persistence would make coverage falsely look unchecked."""
    lineage_id = _seed_requirement(conn)
    document_id = make_document(conn, users["Alex Tan"]["id"])
    _add_chunk(conn, document_id, "map-chunk", "Customer records are stored in a cabinet.")
    _mapping_response(monkeypatch, span=None)

    mapping.map_document(conn, document_id)
    login_as(client, users["Alex Tan"]["id"])
    coverage = client.get(f"/api/v1/documents/{document_id}/coverage")

    assert conn.execute("SELECT COUNT(*) AS count FROM dependencies").fetchone()["count"] == 0
    assert dict(conn.execute("SELECT dependency_found, candidates_seen FROM mapping_passes WHERE document_id = ? AND lineage_id = ?", (document_id, lineage_id)).fetchone()) == {"dependency_found": 0, "candidates_seen": 1}
    assert coverage.status_code == 200
    assert coverage.json()["requirements_checked"] == 1
    assert coverage.json()["dependencies_found"] == 0
    assert coverage.json()["unchecked_lineage_count"] == 0


def test_dependencies_endpoint_scopes_hidden_documents_and_allows_dismissal(client, conn, users):
    """Dropping visibility checks would reveal Priya's dependency to Alex."""
    lineage_id = _seed_requirement(conn)
    priya_document = make_document(conn, users["Priya Menon"]["id"], "Hidden policy")
    _add_chunk(conn, priya_document, "hidden-map-chunk", "Customer records must be retained for 30 g.")
    conn.execute("INSERT INTO dependencies (id, lineage_id, document_chunk_id, document_id, relationship_type, confidence, rationale, evidence_span, evidence_start, evidence_end, created_at) VALUES ('hidden-dependency', ?, 'hidden-map-chunk', ?, 'restates', 0.9, 'Seeded.', '30 g', 33, 37, '2026-01-01T00:00:00+00:00')", (lineage_id, priya_document))
    conn.commit()

    login_as(client, users["Alex Tan"]["id"])
    assert client.get("/api/v1/dependencies", params={"lineage_id": lineage_id}).json()["items"] == []
    assert client.get("/api/v1/dependencies", params={"document_id": priya_document}).status_code == 404
    assert client.patch("/api/v1/dependencies/hidden-dependency", json={"status": "dismissed"}).status_code == 404

    login_as(client, users["Priya Menon"]["id"])
    listed = client.get("/api/v1/dependencies", params={"lineage_id": lineage_id})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == ["hidden-dependency"]
    dismissed = client.patch("/api/v1/dependencies/hidden-dependency", json={"status": "dismissed"})
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
