"""`rosters`, `roster_assignments` and `roster_approvals` tables (§3)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ROSTER_STATUSES = ("DRAFT", "APPROVED")
REVOKE_CAUSES = ("EDIT", "REGENERATE", "CONTRACT_CHANGE", "WORKER_CHANGE")


class Roster(Base):
    __tablename__ = "rosters"
    __table_args__ = (
        UniqueConstraint("month", name="uq_rosters_month"),
        CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_rosters_month_day1"),
        CheckConstraint("status IN ('DRAFT', 'APPROVED')", name="ck_rosters_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="DRAFT")
    forbid_adjacent_shifts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    row_version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    generation_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class RosterAssignment(Base):
    __tablename__ = "roster_assignments"
    __table_args__ = (
        UniqueConstraint(
            "roster_id", "worker_id", "date", "shift", name="uq_roster_assignments_roster_worker_date_shift"
        ),
        Index("ix_roster_assignments_roster_date_shift", "roster_id", "date", "shift"),
        Index("ix_roster_assignments_worker", "worker_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    roster_id: Mapped[int] = mapped_column(ForeignKey("rosters.id", ondelete="CASCADE"), nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False)
    date: Mapped[date] = mapped_column(nullable=False)
    shift: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # slot role, snapshotted (§4.2)


class RosterApproval(Base):
    __tablename__ = "roster_approvals"
    __table_args__ = (
        CheckConstraint(
            "revoke_cause IN ('EDIT', 'REGENERATE', 'CONTRACT_CHANGE', 'WORKER_CHANGE') OR revoke_cause IS NULL",
            name="ck_roster_approvals_revoke_cause",
        ),
        Index("ix_roster_approvals_roster_approved_at", "roster_id", text("approved_at DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    roster_id: Mapped[int] = mapped_column(ForeignKey("rosters.id", ondelete="CASCADE"), nullable=False)
    roster_version: Mapped[int] = mapped_column(nullable=False)
    approved_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    acknowledged_warnings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoke_cause: Mapped[str | None] = mapped_column(String, nullable=True)
    revoke_ref: Mapped[str | None] = mapped_column(String, nullable=True)
