"""Dependencies (section 9.5). Not built yet — arrives with the mapping wave
(PRD build order step 6)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/dependencies", tags=["dependencies"])

_WAVE = "the mapping wave (build order step 6)"


@router.get("")
def list_dependencies(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.post("", status_code=201)
def create_dependency(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.patch("/{dependency_id}")
def patch_dependency(dependency_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)
