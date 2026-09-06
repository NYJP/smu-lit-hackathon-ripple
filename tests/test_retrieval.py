"""Retrieval foundation: extraction, embeddings, hybrid search, and visibility."""

from __future__ import annotations

import json

import fitz

from tests.conftest import install_fake_openai, login_as, make_document


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    result = document.tobytes()
    document.close()
    return result


def _requirement(text: str, *, section: str = "Section 12", subject: str = "record_retention") -> dict:
    return {
        "requirement_text": text,
        "verbatim_text": text,
        "requirement_type": "duration",
        "subject": subject,
        "value": "7 years",
        "value_numeric": 7,
        "value_unit": "years",
        "comparator": "gte",
        "condition": None,
        "exception": None,
        "source_section": section,
        "source_page": 1,
        "effective_date": None,
        "repeals_sections": [],
    }


def _set_extract_response(monkeypatch, requirements: list[dict]) -> None:
    vector = [1.0] + [0.0] * 1535

    def fake_post(url: str, payload: dict, _headers: dict) -> dict:
        if url.endswith("/chat/completions"):
            return {
                "choices": [{"message": {"content": json.dumps({"requirements": requirements})}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125},
            }
        assert url.endswith("/embeddings")
        return {
            "data": [{"index": index, "embedding": vector} for index, _ in enumerate(payload["input"])],
            "usage": {"prompt_tokens": len(payload["input"]), "total_tokens": len(payload["input"])},
        }

    install_fake_openai(monkeypatch, fake_post)


def _upload_regulation(client, title: str, text: str, **form: str):
    return client.post(
        "/api/v1/regulations",
        data={"title": title, "document_kind": "primary", **form},
        files={"file": ("rules.pdf", _pdf_bytes(text), "application/pdf")},
    )


def test_regulation_ingest_extracts_and_persists_requirement_mirrors(client, conn, users, monkeypatch):
    """Removing extraction persistence must leave this regulation without its searchable requirement."""
    _set_extract_response(monkeypatch, [_requirement("Records must be retained for seven years.")])
    login_as(client, users["Priya Menon"]["id"])

    response = _upload_regulation(client, "Retention Rules", "Section 12\nRecords must be retained for seven years.")

    assert response.status_code == 202, response.text
    created = response.json()
    job = client.get(f"/api/v1/jobs/{created['job_id']}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["requirement_count"] == 1
    assert job["result"]["token_usage"] == {"prompt_tokens": 101, "completion_tokens": 25, "total_tokens": 126}
    assert job["result"]["estimated_cost_usd"] > 0

    row = conn.execute(
        """SELECT l.public_ref, l.subject, q.requirement_text, q.source_section, q.source_page,
                  q.value_unit, q.is_current
           FROM requirement_lineages l JOIN regulatory_requirements q ON q.lineage_id = l.id"""
    ).fetchone()
    assert dict(row) == {
        "public_ref": "REQ-001", "subject": "record_retention",
        "requirement_text": "Records must be retained for seven years.",
        "source_section": "Section 12", "source_page": 1, "value_unit": "years", "is_current": 1,
    }
    requirement_id = conn.execute("SELECT id FROM regulatory_requirements").fetchone()["id"]
    assert conn.execute("SELECT requirement_id FROM fts_requirements").fetchone()["requirement_id"] == requirement_id
    assert conn.execute("SELECT requirement_id FROM vec_requirements").fetchone()["requirement_id"] == requirement_id


def test_amendment_reuses_subject_lineage_and_supersedes_current_version(client, conn, users, monkeypatch):
    """Fail if an amended subject creates a second lineage instead of a new version."""
    login_as(client, users["Priya Menon"]["id"])
    _set_extract_response(monkeypatch, [_requirement("Records must be retained for seven years.")])
    original = _upload_regulation(client, "Original", "Section 12\nRecords must be retained for seven years.").json()

    _set_extract_response(monkeypatch, [_requirement("Records must be retained for ten years.")])
    amendment = _upload_regulation(
        client, "Amendment", "Section 12\nRecords must be retained for ten years.",
        document_kind="amendment", amends_regulation_id=original["regulation_id"],
    )

    assert amendment.status_code == 202, amendment.text
    rows = conn.execute(
        "SELECT lineage_id, version, is_current, requirement_text FROM regulatory_requirements ORDER BY version"
    ).fetchall()
    assert [dict(row) for row in rows] == [
        {"lineage_id": rows[0]["lineage_id"], "version": 1, "is_current": 0, "requirement_text": "Records must be retained for seven years."},
        {"lineage_id": rows[0]["lineage_id"], "version": 2, "is_current": 1, "requirement_text": "Records must be retained for ten years."},
    ]
    assert conn.execute("SELECT COUNT(*) AS count FROM requirement_lineages").fetchone()["count"] == 1


def test_amendment_repeal_does_not_retire_same_section_from_another_regulation(client, conn, users, monkeypatch):
    """Fail if a repeal section is applied outside the amended regulation's lineage set."""
    login_as(client, users["Priya Menon"]["id"])
    _set_extract_response(monkeypatch, [_requirement("Keep records for seven years.", subject="record_retention")])
    original = _upload_regulation(client, "Original", "Section 12\nKeep records for seven years.").json()
    _set_extract_response(monkeypatch, [_requirement("Make notices available to each affected customer without delay.", subject="notice_delivery")])
    unrelated_upload = _upload_regulation(client, "Unrelated", "Section 12\nMake notices available to each affected customer without delay.")
    assert unrelated_upload.status_code == 202, unrelated_upload.text
    unrelated_job = client.get(f"/api/v1/jobs/{unrelated_upload.json()['job_id']}").json()
    assert unrelated_job["status"] == "succeeded", unrelated_job
    amendment_requirement = _requirement("Keep records for ten years.", section="Section 13", subject="record_retention")
    amendment_requirement["repeals_sections"] = ["Section 12"]
    _set_extract_response(monkeypatch, [amendment_requirement])

    response = _upload_regulation(client, "Amendment", "Section 13\nKeep records for ten years in the approved records archive.", document_kind="amendment", amends_regulation_id=original["regulation_id"])

    assert response.status_code == 202, response.text
    assert client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()["status"] == "succeeded"
    unrelated = conn.execute("SELECT q.is_current, l.subject FROM regulatory_requirements q JOIN requirement_lineages l ON l.id = q.lineage_id WHERE l.subject = 'notice_delivery'").fetchone()
    assert unrelated is not None and unrelated["is_current"] == 1


def test_search_fuses_retrieval_legs_and_hides_unshared_chunks(client, conn, users, monkeypatch):
    """Fail if retrieval returns a chunk belonging to a document the caller cannot see."""
    vector = [1.0] + [0.0] * 1535
    install_fake_openai(
        monkeypatch,
        lambda _url, _payload, _headers: {"data": [{"index": 0, "embedding": vector}], "usage": {"prompt_tokens": 1, "total_tokens": 1}},
    )
    visible_document = make_document(conn, users["Alex Tan"]["id"], "Visible retention policy")
    hidden_document = make_document(conn, users["Priya Menon"]["id"], "Hidden retention policy")
    conn.executemany(
        """INSERT INTO document_chunks (id, document_id, ordinal, content, section_path, page_number, chunk_type, created_at)
           VALUES (?, ?, 0, ?, 'Retention', 3, 'paragraph', '2026-01-01T00:00:00+00:00')""",
        [
            ("visible-chunk", visible_document, "Keep customer records for seven years."),
            ("hidden-chunk", hidden_document, "Keep confidential customer records for seven years."),
        ],
    )
    conn.executemany(
        "INSERT INTO fts_chunks (chunk_id, content, section_path) VALUES (?, ?, 'Retention')",
        [("visible-chunk", "Keep customer records for seven years."), ("hidden-chunk", "Keep confidential customer records for seven years.")],
    )
    import sqlite_vec

    conn.executemany("INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)", [("visible-chunk", sqlite_vec.serialize_float32(vector)), ("hidden-chunk", sqlite_vec.serialize_float32(vector))])
    conn.execute("INSERT INTO regulations (id, title, document_kind, file_path, file_name, status, created_at) VALUES ('reg-1', 'Rules', 'primary', 'regulations/r.pdf', 'r.pdf', 'ready', '2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO requirement_lineages (id, public_ref, subject, origin_regulation_id, created_at) VALUES ('lineage-1', 'REQ-001', 'record_retention', 'reg-1', '2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO regulatory_requirements (id, lineage_id, regulation_id, requirement_text, requirement_type, subject, is_current, created_at) VALUES ('requirement-1', 'lineage-1', 'reg-1', 'Retain records for seven years.', 'duration', 'record_retention', 1, '2026-01-01T00:00:00+00:00')")
    conn.execute("UPDATE requirement_lineages SET current_version_id = 'requirement-1' WHERE id = 'lineage-1'")
    conn.execute("INSERT INTO fts_requirements (requirement_id, requirement_text, verbatim_text) VALUES ('requirement-1', 'Retain records for seven years.', 'Retain records for seven years.')")
    conn.execute("INSERT INTO vec_requirements (requirement_id, embedding) VALUES ('requirement-1', ?)", (sqlite_vec.serialize_float32(vector),))
    conn.commit()

    login_as(client, users["Alex Tan"]["id"])
    response = client.get("/api/v1/search", params={"q": "customer records retention", "scope": "all"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["chunk_id"] for item in body["chunks"]] == ["visible-chunk"]
    assert body["chunks"][0]["section_path"] == "Retention"
    assert body["chunks"][0]["page_number"] == 3
    assert body["chunks"][0]["score"] > 0
    assert body["requirements"] == [{
        "lineage_id": "lineage-1", "public_ref": "REQ-001",
        "requirement_text": "Retain records for seven years.", "source_section": None,
        "score": body["requirements"][0]["score"],
    }]


def test_search_requires_configured_key_only_when_used(client, users, monkeypatch):
    """Fail if semantic search silently falls back when the required key is absent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    login_as(client, users["Alex Tan"]["id"])

    response = client.get("/api/v1/search", params={"q": "retention"})

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "unavailable", "message": "OPENAI_API_KEY is required for retrieval.", "details": None,
    }


def test_current_requirements_endpoint_returns_lineage_read_model(client, conn, users):
    """Fail if the requirements endpoint remains a stub after extraction creates a lineage."""
    conn.execute("INSERT INTO regulations (id, title, document_kind, file_path, file_name, status, created_at) VALUES ('reg-read', 'Rules', 'primary', 'regulations/r.pdf', 'r.pdf', 'ready', '2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO requirement_lineages (id, public_ref, subject, origin_regulation_id, created_at) VALUES ('lineage-read', 'REQ-004', 'record_retention', 'reg-read', '2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO regulatory_requirements (id, lineage_id, regulation_id, requirement_text, requirement_type, subject, value, source_section, is_current, created_at) VALUES ('requirement-read', 'lineage-read', 'reg-read', 'Retain records for seven years.', 'duration', 'record_retention', '7 years', 'Section 4', 1, '2026-01-01T00:00:00+00:00')")
    conn.execute("UPDATE requirement_lineages SET current_version_id = 'requirement-read' WHERE id = 'lineage-read'")
    conn.commit()
    login_as(client, users["Alex Tan"]["id"])

    response = client.get("/api/v1/requirements", params={"q": "retention"})

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [{
        "lineage_id": "lineage-read", "public_ref": "REQ-004",
        "requirement_text": "Retain records for seven years.", "requirement_type": "duration",
        "subject": "record_retention", "value": "7 years", "source_section": "Section 4",
        "version": 1, "dependency_count": 0,
    }], "next_cursor": None}
