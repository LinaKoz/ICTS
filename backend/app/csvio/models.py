"""`csv_imports` table (§3): preview → confirm workflow for CSV import (T6)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CSV_IMPORT_STATUSES = ("PENDING", "CONFIRMED")


class CsvImport(Base):
    __tablename__ = "csv_imports"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'CONFIRMED')", name="ck_csv_imports_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="PENDING")
    preview: Mapped[dict] = mapped_column(JSONB, nullable=False)  # rows, classifications, base fingerprints
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
