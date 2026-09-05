"""Recommendations (section 9.6). Not built yet — arrives with the
recommendations wave (PRD build order step 11)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

_WAVE = "the recommendations wave (build order step 11)"


@router.patch("/{recommendation_id}")
def patch_recommendation(recommendation_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)
