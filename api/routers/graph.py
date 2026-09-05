"""Dependency graph (section 9.11). Not built yet — arrives with the
dependency graph wave (PRD build order step 10), which needs both step 6
(current-state mode) and step 7 (change-reach mode) in place first."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("")
def get_graph(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented("the dependency graph wave (build order step 10)")
