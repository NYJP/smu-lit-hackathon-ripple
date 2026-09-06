"""Admin-only local environment controls."""
from __future__ import annotations
from api.sqlite_driver import sqlite3
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from api.access import require_admin
from api.db import get_db
from api.services import environment

router = APIRouter(prefix="/settings", tags=["settings"])

class SampleEnvironmentIn(BaseModel):
    scenario_id: str = "pdpf"

@router.post("/reset")
def reset_environment(conn: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(require_admin)):
    environment.reset(conn)
    return {"status": "reset"}

@router.post("/sample-environment")
def load_sample_environment(payload: SampleEnvironmentIn | None = None, conn: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(require_admin)):
    return {"status": "loaded", **environment.load_sample(conn, payload.scenario_id if payload else "pdpf")}

@router.get("/sample-environments")
def sample_environments(_admin: sqlite3.Row = Depends(require_admin)):
    return {"items": environment.list_scenarios()}
