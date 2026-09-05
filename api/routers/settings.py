"""Admin-only local environment controls."""
from __future__ import annotations
import sqlite3
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from api.access import require_admin
from api.db import get_db
from api.errors import ApiError
from api.services import environment

router = APIRouter(prefix="/settings", tags=["settings"])

class Confirmation(BaseModel):
    confirmation: str

def _confirm(payload: Confirmation) -> None:
    if payload.confirmation != "RESET":
        raise ApiError(422, "validation_error", "Type RESET to confirm this action.")

@router.post("/reset")
def reset_environment(payload: Confirmation, conn: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(require_admin)):
    _confirm(payload)
    environment.reset(conn)
    return {"status": "reset"}

@router.post("/sample-environment")
def load_sample_environment(payload: Confirmation, conn: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(require_admin)):
    _confirm(payload)
    return {"status": "loaded", **environment.load_sample(conn)}
