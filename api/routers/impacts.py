"""Impacts (section 9.6). Not built yet — arrives with the impact engine
wave (PRD build order step 7)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/impacts", tags=["impacts"])

_WAVE = "the impact engine wave (build order step 7)"


@router.get("/{impact_id}")
def get_impact(impact_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.patch("/{impact_id}")
def patch_impact(impact_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.post("/{impact_id}/recommendation", status_code=201)
def generate_recommendation(impact_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented("the recommendations wave (build order step 11)")
