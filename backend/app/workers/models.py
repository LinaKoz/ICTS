"""`workers` and `worker_field_history` tables (§3).

`worker_field_history` is insert-only: a database trigger (added in the
migration, alongside `contract_versions`' trigger) rejects UPDATE and
DELETE. See §3 "Worker status/role history (D9)".
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

WORKER_ROLES = ("GENERAL_GUARD", "SCREENER", "SUPERVISOR")
WORKER_STATUSES = ("ACTIVE", "INACTIVE")
HISTORY_FIELDS = ("STATUS", "ROLE")

NATIONAL_ID_REGEX = r"^[0-9]{9}$"


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        CheckConstraint(f"national_id ~ '{NATIONAL_ID_REGEX}'", name="ck_workers_national_id_format"),
        CheckConstraint("role IN ('GENERAL_GUARD', 'SCREENER', 'SUPERVISOR')", name="ck_workers_role"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_workers_status"),
        Index("ix_workers_status_role", "status", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    national_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    row_version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkerFieldHistory(Base):
    """Insert-only (§3): every PATCH that changes `status` or `role`
    inserts one row here, in the same transaction as the worker update.
    No UPDATE/DELETE (enforced by a trigger, as `contract_versions`)."""

    __tablename__ = "worker_field_history"
    __table_args__ = (
        CheckConstraint("field IN ('STATUS', 'ROLE')", name="ck_worker_field_history_field"),
        Index(
            "ix_worker_field_history_worker_field_effective",
            "worker_id",
            "field",
            text("effective_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(
        # RESTRICT (§3): history must outlive the worker row it is about.
        ForeignKey("workers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    field: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[str] = mapped_column(String, nullable=False)
    new_value: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
