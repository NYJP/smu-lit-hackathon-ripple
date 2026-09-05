"""Scans (section 9.10 / section 8.5). Not built yet — arrives with the
scanning wave (PRD build order step 8).

`POST /scans` is one write endpoint whose role gate is specified precisely
enough to enforce ahead of the engine: "scope='full' is admin-only" (section
9.10). Any member may request a `stale` (default) scan; only an admin may
request `full`. That check runs before the 501, so acceptance criterion 41's
"...or requesting a full scan receives 403" already holds.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from api.auth import get_current_user
from api.errors import ApiError, not_implemented

router = APIRouter(prefix="/scans", tags=["scans"])

_WAVE = "the scanning wave (build order step 8)"


class ScanCreate(BaseModel):
    scope: str | None = None
    scope_id: str | None = None
    confirm: bool | None = None


@router.get("/pending")
def scans_pending(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.post("", status_code=202)
def create_scan(
    user: sqlite3.Row = Depends(get_current_user),
    payload: ScanCreate | None = Body(default=None),
):
    scope = (payload.scope if payload else None) or "stale"
    if scope == "full" and user["role"] != "admin":
        raise ApiError(403, "forbidden", "A full re-scan requires an admin account.")
    not_implemented(_WAVE)


@router.get("")
def list_scans(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("/{scan_id}")
def get_scan(scan_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)
