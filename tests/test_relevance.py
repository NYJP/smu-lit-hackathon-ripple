from __future__ import annotations

import uuid
from datetime import datetime, timezone

from api.services.relevance import relevance_for
from tests.conftest import add_collaborator, make_document


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_relevance_precedence_and_workspace_fallback(conn, users):
    priya, alex = users["Priya Menon"], users["Alex Tan"]
    owned = make_document(conn, priya["id"], "Owned")
    shared = make_document(conn, alex["id"], "Shared")
    followed = make_document(conn, alex["id"], "Followed")
    other = make_document(conn, alex["id"], "Other")
    add_collaborator(conn, shared, priya["id"], "reviewer", alex["id"])
    conn.execute("INSERT INTO follows(user_id,subject_type,subject_id,created_at) VALUES (?,'document',?,?)", (priya["id"], followed, _now()))
    conn.commit()

    result = relevance_for(conn, priya["id"], [owned, shared, followed, other])
    assert result[owned] == {"reason": "You own this document.", "weight": 5}
    assert result[shared]["weight"] == 3
    assert result[followed]["weight"] == 1
    assert result[other]["weight"] == 0


def test_owner_beats_every_lower_signal(conn, users):
    priya = users["Priya Menon"]
    document = make_document(conn, priya["id"], "Everything")
    team_id = uuid.uuid4().hex
    conn.execute("INSERT INTO teams(id,name,created_at) VALUES (?,?,?)", (team_id, "Privacy", _now()))
    conn.execute("INSERT INTO team_members(team_id,user_id,added_at) VALUES (?,?,?)", (team_id, priya["id"], _now()))
    conn.execute("INSERT INTO document_teams(document_id,team_id,assigned_at) VALUES (?,?,?)", (document, team_id, _now()))
    conn.execute("INSERT INTO follows(user_id,subject_type,subject_id,created_at) VALUES (?,'document',?,?)", (priya["id"], document, _now()))
    conn.commit()
    assert relevance_for(conn, priya["id"], [document])[document]["weight"] == 5
