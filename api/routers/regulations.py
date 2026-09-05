"""Regulations (section 9.1). Not built yet — arrives with the ingestion &
extraction wave (PRD build order steps 3, 5, and 9).

The role gate is real even though the body of each handler is a stub:
regulations are writable by admins only (section 5.5 resource matrix), so a
member posting here must already get 403 rather than waiting for step 3 to
land before that rule is enforced (acceptance criterion 41).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.access import require_admin
from api.auth import get_current_user
from api.db import get_db
from api.errors import not_implemented

router = APIRouter(prefix="/regulations", tags=["regulations"])

_WAVE = "the ingestion & extraction wave (build order steps 3, 5, and 9)"


@router.post("", status_code=202)
def upload_regulation(
    _admin: sqlite3.Row = Depends(require_admin),
    _conn: sqlite3.Connection = Depends(get_db),
):
    not_implemented(_WAVE)


@router.get("")
def list_regulations(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("/{regulation_id}")
def get_regulation(regulation_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.delete("/{regulation_id}", status_code=204)
def delete_regulation(regulation_id: str, _admin: sqlite3.Row = Depends(require_admin)):
    not_implemented(_WAVE)
