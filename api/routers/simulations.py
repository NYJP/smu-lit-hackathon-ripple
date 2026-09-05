"""Simulations (section 9.7). Not built yet — arrives with the impact
engine wave (PRD build order step 7), which is deliberately built before
amendment upload (section 13)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/simulations", tags=["simulations"])

_WAVE = "the impact engine wave (build order step 7)"


@router.post("", status_code=201)
def create_simulation(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("")
def list_simulations(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("/{simulation_id}")
def get_simulation(simulation_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.patch("/{simulation_id}")
def patch_simulation(simulation_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.post("/{simulation_id}/estimate")
def estimate_simulation(simulation_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.post("/{simulation_id}/run", status_code=202)
def run_simulation(simulation_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.post("/{simulation_id}/promote")
def promote_simulation(simulation_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.delete("/{simulation_id}", status_code=204)
def delete_simulation(simulation_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)
