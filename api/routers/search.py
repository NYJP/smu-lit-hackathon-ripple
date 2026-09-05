"""Semantic search (section 9.8 / section 7.5). Not built yet — arrives
with the embeddings & search wave (PRD build order step 4), the first
demoable milestone."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.errors import not_implemented

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(_user: sqlite3.Row = Depends(get_current_user)):
    not_implemented("the embeddings & search wave (build order step 4)")
