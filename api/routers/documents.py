"""Documents (section 9.3). Not built yet — arrives with the ingestion and
mapping wave (PRD build order steps 3 and 6).

Every real handler here will need to resolve visibility through
`access.visible_document_ids` / `access.require_visible_document` before it
does anything else, per section 11 ("Scoping is one function"). That logic
has nothing to scope against yet — there is no document table content —
so these stay honest 501s rather than pretending to enforce a rule with no
data behind it.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/documents", tags=["documents"])

_WAVE = "the ingestion and mapping wave (build order steps 3 and 6)"


@router.post("", status_code=202)
def upload_documents(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("")
def list_documents(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("/{document_id}/coverage")
def document_coverage(document_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.post("/{document_id}/collaborators")
def add_collaborators(document_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.delete("/{document_id}/collaborators/{user_id}", status_code=204)
def remove_collaborator(document_id: str, user_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.patch("/{document_id}")
def patch_document(document_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("/{document_id}")
def get_document(document_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)
