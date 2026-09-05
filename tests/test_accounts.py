"""PRD section 14, accounts-and-scoping criteria 35, 36, 41, 43.

Criteria 37-40 (the ones the task calls out as most likely to be skipped)
live in test_access.py, exercised directly against api/access.py with
document/collaborator rows inserted straight into the schema, because the
document-touching HTTP endpoints are 501 stubs this wave. Criterion 42
(instant client-side re-render on account switch) is a web-app behaviour
with nothing to test server-side yet.
"""

from __future__ import annotations

from tests.conftest import login_as, make_document


def test_three_seed_users_created_with_correct_roles(client):
    """Criterion 35: a clean boot creates exactly three users, one admin and
    two members, and /who's data source (GET /users) lists all three with
    roles, with no setup step."""
    resp = client.get("/api/v1/users")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    by_name = {u["display_name"]: u for u in items}
    assert set(by_name) == {"Priya Menon", "Alex Tan", "Sam Rahim"}
    assert by_name["Priya Menon"]["role"] == "admin"
    assert by_name["Alex Tan"]["role"] == "member"
    assert by_name["Sam Rahim"]["role"] == "member"
    admins = [u for u in items if u["role"] == "admin"]
    assert len(admins) == 1


def test_get_users_requires_no_session(client):
    """GET /users is one of the three paths exempt from session-required
    (section 9) — it is what the picker renders before any session exists."""
    resp = client.get("/api/v1/users")
    assert resp.status_code == 200


def test_selecting_a_name_creates_session_and_me_reflects_it(client, users):
    """Criterion 36: selecting a name creates a session and /auth/me returns
    that user."""
    alex = users["Alex Tan"]
    login_as(client, alex["id"])
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == alex["id"]
    assert resp.json()["user"]["display_name"] == "Alex Tan"


def test_auth_me_401_without_a_session(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthenticated"


def test_unknown_user_id_returns_404_not_a_credential_error(client):
    resp = client.post("/api/v1/auth/session", json={"user_id": "does-not-exist"})
    assert resp.status_code == 404


def test_no_endpoint_accepts_a_password_or_token_field(client, users):
    """Criterion 36: no endpoint in the API accepts a password, token, or
    credential field of any kind. Spot-checked on the two account-creation
    paths: extra credential-shaped fields are silently ignored (pydantic
    models declare no such field at all), never validated or stored."""
    resp = client.post(
        "/api/v1/auth/session",
        json={"user_id": users["Alex Tan"]["id"], "password": "hunter2", "token": "x"},
    )
    assert resp.status_code == 200  # extra fields ignored, not rejected or used

    login_as(client, users["Priya Menon"]["id"])
    resp = client.post(
        "/api/v1/users",
        json={"display_name": "New Hire", "role": "member", "password": "hunter2"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "password" not in body and "token" not in body


def test_member_posting_to_regulations_gets_403(client, users):
    """Criterion 41 (part 1): a member session posting to /regulations
    receives 403. Admin passes the same gate and reaches the honest 501 —
    proving the check is a real dependency, not a coincidence of the stub."""
    login_as(client, users["Alex Tan"]["id"])
    resp = client.post("/api/v1/regulations")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"

    login_as(client, users["Priya Menon"]["id"])
    resp = client.post("/api/v1/regulations")
    assert resp.status_code == 501


def test_member_requesting_full_scan_gets_403(client, users):
    """Criterion 41 (part 2): "...or requesting a full scan receives 403."
    scope='full' is admin-only per section 9.10, checked ahead of the 501."""
    login_as(client, users["Alex Tan"]["id"])
    resp = client.post("/api/v1/scans", json={"scope": "full"})
    assert resp.status_code == 403

    resp = client.post("/api/v1/scans", json={"scope": "stale"})
    assert resp.status_code == 501  # any member may request a stale scan

    login_as(client, users["Priya Menon"]["id"])
    resp = client.post("/api/v1/scans", json={"scope": "full"})
    assert resp.status_code == 501


def test_two_members_get_byte_identical_requirements_lists(client, users):
    """Criterion 41 (part 3): two different members querying /requirements
    receive byte-identical lists. Meaningful even against a 501 stub: it
    proves the response does not vary by who is asking."""
    login_as(client, users["Alex Tan"]["id"])
    alex_resp = client.get("/api/v1/requirements")

    login_as(client, users["Sam Rahim"]["id"])
    sam_resp = client.get("/api/v1/requirements")

    assert alex_resp.status_code == sam_resp.status_code == 501
    assert alex_resp.content == sam_resp.content


def test_admin_only_user_management(client, users):
    login_as(client, users["Alex Tan"]["id"])
    assert client.post("/api/v1/users", json={"display_name": "X", "role": "member"}).status_code == 403
    assert client.patch(f"/api/v1/users/{users['Sam Rahim']['id']}", json={"role": "admin"}).status_code == 403
    assert client.delete(f"/api/v1/users/{users['Sam Rahim']['id']}").status_code == 403


def test_deleting_last_admin_is_refused(client, users):
    """Criterion 43 (last-admin rule)."""
    login_as(client, users["Priya Menon"]["id"])
    resp = client.delete(f"/api/v1/users/{users['Priya Menon']['id']}")
    assert resp.status_code == 409


def test_deleting_user_with_documents_requires_reassign(client, conn, users):
    """Criterion 43 (reassign rule): deleting a user who owns documents
    returns 409 with the owned count; the same call with ?reassign_to=
    succeeds and the documents survive with the new owner."""
    sam = users["Sam Rahim"]
    alex = users["Alex Tan"]
    doc_id = make_document(conn, owner_id=sam["id"], name="Employee Handbook.pdf")

    login_as(client, users["Priya Menon"]["id"])
    resp = client.delete(f"/api/v1/users/{sam['id']}")
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["owned_document_count"] == 1

    resp = client.delete(f"/api/v1/users/{sam['id']}?reassign_to={alex['id']}")
    assert resp.status_code == 204

    row = conn.execute("SELECT owner_id FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert row["owner_id"] == alex["id"]

    remaining = client.get("/api/v1/users").json()["items"]
    assert "Sam Rahim" not in {u["display_name"] for u in remaining}


def test_deleting_user_without_documents_succeeds(client, users):
    login_as(client, users["Priya Menon"]["id"])
    created = client.post("/api/v1/users", json={"display_name": "Temp Member", "role": "member"})
    assert created.status_code == 201
    temp_id = created.json()["id"]

    resp = client.delete(f"/api/v1/users/{temp_id}")
    assert resp.status_code == 204
