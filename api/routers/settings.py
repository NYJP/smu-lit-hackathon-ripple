"""Admin-only local environment controls."""
from __future__ import annotations
import sqlite3
from fastapi import APIRouter, Depends
from api.access import require_admin
from api.db import get_db
from api.services import environment

router = APIRouter(prefix="/settings", tags=["settings"])

@router.post("/reset")
def reset_environment(conn: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(require_admin)):
    environment.reset(conn)
    return {"status": "reset"}

@router.post("/sample-environment")
def load_sample_environment(conn: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(require_admin)):
    return {"status": "loaded", **environment.load_sample(conn)}
