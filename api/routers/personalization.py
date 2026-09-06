"""Teams, follows, and notifications used by personalized work views."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api import access
from api.auth import get_current_user
from api.db import get_db
from api.errors import ApiError

router = APIRouter(tags=["personalization"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TeamAssignment(BaseModel):
    team_ids: list[str]


class FollowIn(BaseModel):
    subject_type: Literal["document", "regulation", "lineage"]
    subject_id: str
    following: bool = True


class NotificationPatch(BaseModel):
    read: bool


@router.get("/teams")
def teams(conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    rows = conn.execute(
        """SELECT t.*, COUNT(DISTINCT tm.user_id) AS member_count,
                  MAX(CASE WHEN tm.user_id=? THEN 1 ELSE 0 END) AS is_member
             FROM teams t LEFT JOIN team_members tm ON tm.team_id=t.id
            GROUP BY t.id ORDER BY t.name COLLATE NOCASE""",
        (user["id"],),
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/documents/{document_id}/teams")
def assign_teams(document_id: str, payload: TeamAssignment, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    access.require_document_write(conn, user, document_id)
    team_ids = list(dict.fromkeys(payload.team_ids))
    if team_ids:
        placeholders = ",".join("?" * len(team_ids))
        found = conn.execute(f"SELECT id FROM teams WHERE id IN ({placeholders})", team_ids).fetchall()
        if len(found) != len(team_ids):
            raise ApiError(404, "not_found", "Team not found.")
    conn.execute("DELETE FROM document_teams WHERE document_id=?", (document_id,))
    conn.executemany(
        "INSERT INTO document_teams(document_id,team_id,assigned_at) VALUES (?,?,?)",
        [(document_id, team_id, _now()) for team_id in team_ids],
    )
    conn.commit()
    return {"team_ids": team_ids}


@router.put("/follows")
def put_follow(payload: FollowIn, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    if payload.following:
        conn.execute(
            "INSERT OR IGNORE INTO follows(user_id,subject_type,subject_id,created_at) VALUES (?,?,?,?)",
            (user["id"], payload.subject_type, payload.subject_id, _now()),
        )
    else:
        conn.execute(
            "DELETE FROM follows WHERE user_id=? AND subject_type=? AND subject_id=?",
            (user["id"], payload.subject_type, payload.subject_id),
        )
    conn.commit()
    return {"following": payload.following}


@router.get("/notifications")
def notifications(limit: int = 30, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    if not 1 <= limit <= 100:
        raise ApiError(422, "validation_error", "limit must be between 1 and 100.")
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY rowid DESC LIMIT ?",
        (user["id"], limit),
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.patch("/notifications/{notification_id}")
def patch_notification(notification_id: str, payload: NotificationPatch, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(get_current_user)):
    row = conn.execute("SELECT id FROM notifications WHERE id=? AND user_id=?", (notification_id, user["id"])).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "Notification not found.")
    conn.execute("UPDATE notifications SET read_at=? WHERE id=?", (_now() if payload.read else None, notification_id))
    conn.commit()
    return {"id": notification_id, "read": payload.read}
