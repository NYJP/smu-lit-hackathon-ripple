"""Requirements (section 9.2). Not built yet — arrives with the extraction
and mapping wave (PRD build order steps 5-7).

`PATCH /requirements/{lineage_id}` writes a requirement lineage/version, so
it is admin-only per the resource matrix; reads and the simulate shorthand
are open to every signed-in member.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.access import require_admin
from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/requirements", tags=["requirements"])

_WAVE = "the extraction and mapping wave (build order steps 5-7)"


@router.get("")
def list_requirements(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("/{lineage_id}")
def get_requirement(lineage_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.patch("/{lineage_id}")
def patch_requirement(lineage_id: str, _admin: sqlite3.Row = Depends(require_admin)):
    not_implemented(_WAVE)


@router.post("/{lineage_id}/simulate", status_code=202)
def simulate_requirement(lineage_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented("the impact engine wave (build order step 7)")
