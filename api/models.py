"""Pydantic request/response models.

Shared request and response models. Account role input remains backwards
compatible, but this product build normalizes every account to admin.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["admin", "member"]


class UserOut(BaseModel):
    id: str
    display_name: str
    role: Role
    document_count: int
    last_seen_at: str | None = None


class UsersListOut(BaseModel):
    items: list[UserOut]


class UserCreate(BaseModel):
    # No password field, ever (section 5.5 / 11 — "no credentials anywhere").
    display_name: str = Field(min_length=1, max_length=200)
    role: Role = "admin"


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None


class SessionCreate(BaseModel):
    # Deliberately just an id: choosing a name is not authenticating.
    user_id: str


class MeUser(BaseModel):
    id: str
    display_name: str
    role: Role


class MeOut(BaseModel):
    user: MeUser


class SessionOut(BaseModel):
    user: MeUser
