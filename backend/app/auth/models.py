"""`users` table (§3): username/password auth, app_role for `require_role()`."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

APP_ROLES = ("PLANNER", "MANAGER")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("app_role IN ('PLANNER', 'MANAGER')", name="ck_users_app_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    app_role: Mapped[str] = mapped_column(String, nullable=False)
