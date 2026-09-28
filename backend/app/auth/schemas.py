"""Pydantic request/response models for `/auth/*` (§6)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    app_role: Literal["PLANNER", "MANAGER"]
