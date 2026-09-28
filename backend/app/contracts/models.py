"""`contract_versions` table (§3): immutable, versioned per worker/month.

Rows are never updated or deleted after insert; a database trigger
(added in the migration) rejects UPDATE and DELETE. Revisions are new
rows with a higher `version_no` (P1).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CONTRACT_SOURCES = ("UI", "CSV")


class ContractVersion(Base):
    __tablename__ = "contract_versions"
    __table_args__ = (
        UniqueConstraint("worker_id", "version_no", name="uq_contract_versions_worker_version"),
        CheckConstraint("EXTRACT(DAY FROM effective_month) = 1", name="ck_contract_versions_month_day1"),
        CheckConstraint(
            "0 <= min_hours AND min_hours <= max_hours AND max_hours <= 744",
            name="ck_contract_versions_hours",
        ),
        CheckConstraint("hourly_rate_ils > 0", name="ck_contract_versions_rate_positive"),
        CheckConstraint("source IN ('UI', 'CSV')", name="ck_contract_versions_source"),
        Index(
            "ix_contract_versions_worker_effective_version",
            "worker_id",
            text("effective_month DESC"),
            text("version_no DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False)
    version_no: Mapped[int] = mapped_column(nullable=False)
    effective_month: Mapped[date] = mapped_column(nullable=False)
    hourly_rate_ils: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    min_hours: Mapped[int] = mapped_column(nullable=False)
    max_hours: Mapped[int] = mapped_column(nullable=False)
    availability: Mapped[list] = mapped_column(JSONB, nullable=False)  # sorted ["MON:A", ...]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("csv_imports.id"), nullable=True)
