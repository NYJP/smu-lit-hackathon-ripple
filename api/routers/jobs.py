"""Jobs (section 9.8 / section 5.4). Not built yet — the `jobs` table exists
(section 6) but the BackgroundTasks runner that writes to it arrives with
the ingestion wave (PRD build order step 3)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/jobs", tags=["jobs"])

_WAVE = "the ingestion wave's job runner (build order step 3)"


@router.get("/{job_id}")
def get_job(job_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)


@router.get("")
def list_jobs(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented(_WAVE)
