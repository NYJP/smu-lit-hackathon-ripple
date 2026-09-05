"""PRD section 14, criteria 37-40 — the ones flagged as most likely to be
skipped. The document-touching HTTP endpoints (documents, dependencies,
impacts, recommendations) are honest 501 stubs this wave, so there is no
router yet to hit with a real HTTP request and observe a 404-vs-403
distinction. What IS real and load-bearing right now is api/access.py — the
single accessor every future router must call (section 11: "Scoping is one
function") — so these tests exercise it directly against document and
document_collaborator rows inserted straight into the schema, per the task's
own instruction to do exactly that.
"""

from __future__ import annotations

from api import access
from api.errors import ApiError
from tests.conftest import add_collaborator, make_document

import pytest


def test_owner_sees_own_document_others_do_not(conn, users):
    """Basis for criterion 37/38: a document is visible to its owner and
    invisible to an unrelated member."""
    priya = users["Priya Menon"]
    alex = users["Alex Tan"]
    doc_id = make_document(conn, owner_id=priya["id"], name="Data Retention Policy.pdf")

    assert doc_id in access.visible_document_ids(conn, priya)
    assert doc_id not in access.visible_document_ids(conn, alex)


def test_admin_sees_every_document_regardless_of_owner(conn, users):
    """Criterion 38's admin clause: an admin's visible set is the whole
    corpus, not just their own documents."""
    priya = users["Priya Menon"]  # admin
    alex = users["Alex Tan"]
    sam = users["Sam Rahim"]

    alex_doc = make_document(conn, owner_id=alex["id"], name="Customer Data SOP.docx")
    sam_doc = make_document(conn, owner_id=sam["id"], name="Employee Handbook.pdf")

    visible_to_admin = access.visible_document_ids(conn, priya)
    assert alex_doc in visible_to_admin
    assert sam_doc in visible_to_admin


def test_member_visible_set_excludes_everything_not_owned_or_tagged(conn, users):
    """Criterion 38: as Alex, nothing belonging to Priya appears in the
    computed visible set — this is what every list/search/dashboard/graph
    endpoint will filter through once built."""
    priya = users["Priya Menon"]
    alex = users["Alex Tan"]
    sam = users["Sam Rahim"]

    priya_doc_1 = make_document(conn, owner_id=priya["id"], name="Data Retention Policy.pdf")
    priya_doc_2 = make_document(conn, owner_id=priya["id"], name="Privacy Playbook.pdf")
    sam_doc = make_document(conn, owner_id=sam["id"], name="Employee Handbook.pdf")
    alex_doc = make_document(conn, owner_id=alex["id"], name="Customer Data SOP.docx")

    visible_to_alex = access.visible_document_ids(conn, alex)
    assert visible_to_alex == {alex_doc}
    assert priya_doc_1 not in visible_to_alex
    assert priya_doc_2 not in visible_to_alex
    assert sam_doc not in visible_to_alex


def test_tagged_collaborator_gains_visibility(conn, users):
    """Criterion 39: a user tagged on a document sees it under Shared with
    me — i.e. it joins their visible set — regardless of viewer/reviewer
    access level. Uses two plain members (not the admin, who would already
    see every document regardless of tagging) so the tagging mechanism
    itself is what the assertion exercises."""
    alex = users["Alex Tan"]
    sam = users["Sam Rahim"]
    doc_id = make_document(conn, owner_id=alex["id"], name="Customer Data SOP.docx")

    assert doc_id not in access.visible_document_ids(conn, sam)

    add_collaborator(conn, doc_id, user_id=sam["id"], access="reviewer", added_by=alex["id"])

    assert doc_id in access.visible_document_ids(conn, sam)


def test_require_visible_document_is_404_not_403_for_hidden_document(conn, users):
    """Criterion 37, verbatim: "As Alex, requesting one of Priya's documents
    ... by id returns 404, not 403 — the response must not confirm that the
    resource exists." Also proves a hidden document and a genuinely
    nonexistent id produce the identical error shape."""
    priya = users["Priya Menon"]
    alex = users["Alex Tan"]
    hidden_doc = make_document(conn, owner_id=priya["id"], name="Privacy Playbook.pdf")

    with pytest.raises(ApiError) as hidden_exc:
        access.require_visible_document(conn, alex, hidden_doc)
    assert hidden_exc.value.status_code == 404
    assert hidden_exc.value.code == "not_found"

    with pytest.raises(ApiError) as missing_exc:
        access.require_visible_document(conn, alex, "not-a-real-id")
    assert missing_exc.value.status_code == 404
    assert missing_exc.value.code == "not_found"

    # Same status, same code, same message — Alex cannot distinguish
    # "exists but hidden" from "does not exist" by the shape of the error.
    assert hidden_exc.value.message == missing_exc.value.message


def test_viewer_collaborator_cannot_write_reviewer_can(conn, users):
    """Criterion 40: a viewer collaborator cannot change an impact's review
    status or accept a recommendation; a reviewer can. Both actions gate on
    can_write_document / require_document_write in every future router
    (section 5.5 resource matrix: impacts/recommendations 'follow the
    document')."""
    priya = users["Priya Menon"]
    sam = users["Sam Rahim"]
    doc_id = make_document(conn, owner_id=priya["id"], name="Data Retention Policy.pdf")

    add_collaborator(conn, doc_id, user_id=sam["id"], access="viewer", added_by=priya["id"])
    assert access.is_document_visible(conn, sam, doc_id) is True
    assert access.can_write_document(conn, sam, doc_id) is False
    with pytest.raises(ApiError) as exc:
        access.require_document_write(conn, sam, doc_id)
    assert exc.value.status_code == 403  # visible, just not writable

    conn.execute(
        "UPDATE document_collaborators SET access = 'reviewer' WHERE document_id = ? AND user_id = ?",
        (doc_id, sam["id"]),
    )
    conn.commit()
    assert access.can_write_document(conn, sam, doc_id) is True
    access.require_document_write(conn, sam, doc_id)  # does not raise


def test_owner_and_admin_can_always_write(conn, users):
    priya = users["Priya Menon"]  # admin
    alex = users["Alex Tan"]
    doc_id = make_document(conn, owner_id=alex["id"], name="DPA Template.docx")

    assert access.can_write_document(conn, alex, doc_id) is True  # owner
    assert access.can_write_document(conn, priya, doc_id) is True  # admin, not owner/tagged


def test_can_write_document_false_for_nonexistent_document(conn, users):
    assert access.can_write_document(conn, users["Alex Tan"], "not-a-real-id") is False
