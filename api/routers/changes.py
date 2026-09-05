"""Changes, impacts, recommendations feed (section 9.6). Not built yet —
arrives with the impact engine and amendment-detection wave (PRD build
order steps 7 and 9)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/changes", tags=["changes"])

_WAVE = "the impact engine and amendment-detection wave (build order steps 7 and 9)"


@router.get("")
def list_changes(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("/{change_id}")
def get_change(change_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.post("/{change_id}/analyse", status_code=202)
def analyse_change(change_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("/{change_id}/impacts")
def list_change_impacts(change_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)
