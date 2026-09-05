"""File streaming (section 9.4). Not built yet — arrives with the ingestion
wave (PRD build order step 3), once regulations/documents actually have
files on disk at `./data/files/{kind}/` to stream back."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{kind}/{file_id}")
def get_file(kind: str, file_id: str, _user: sqlite3.Row = Depends(get_current_user)):
    not_implemented("the ingestion wave (build order step 3)")
