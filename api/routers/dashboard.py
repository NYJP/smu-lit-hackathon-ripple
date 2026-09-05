"""Dashboard (section 9.8). Not built yet — arrives with the impact engine
wave (PRD build order step 7), the earliest point at which totals, recent
changes, and an attention panel are all meaningful."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented("the impact engine wave (build order step 7)")
