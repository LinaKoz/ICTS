"""CSV export (P13, P14): one row per worker with the contract effective
for the chosen month, otherwise the next future version. Workers with no
applicable contract are still exported, with the contract columns empty
(D10). Every row carries `export_format=icts-export-v1`; names starting
with a formula trigger get one leading apostrophe (`parse.escape_name`)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.models import ContractVersion
from app.contracts.resolve import resolve_contracts_for_workers
from app.csvio.parse import EXPORT_FORMAT, TRIGGERS, escape_name, per_day_form
from app.workers.models import Worker

EXPORT_COLUMNS = (
    "national_id",
    "full_name",
    "role",
    "status",
    "effective_month",
    "hourly_rate_ils",
    "min_monthly_hours",
    "max_monthly_hours",
    "availability",
    "export_format",
)
BOM = "﻿"


@dataclass
class ExportResult:
    content: bytes
    worker_count: int
    no_contract_count: int


async def _next_future(session: AsyncSession, worker_ids: list[int], month: date) -> dict[int, ContractVersion]:
    """The earliest-effective version after `month` (highest version_no within
    that month), for workers with nothing resolved at `month`."""
    if not worker_ids:
        return {}
    stmt = (
        select(ContractVersion)
        .where(ContractVersion.worker_id.in_(worker_ids), ContractVersion.effective_month > month)
        .order_by(ContractVersion.worker_id, ContractVersion.effective_month.asc(), ContractVersion.version_no.desc())
    )
    out: dict[int, ContractVersion] = {}
    for cv in (await session.execute(stmt)).scalars():
        out.setdefault(cv.worker_id, cv)
    return out


def _safe(value: str) -> str:
    assert not value or value[0] not in TRIGGERS, f"exported field would start with a formula trigger: {value!r}"
    return value


def render_csv(rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return (BOM + buf.getvalue()).encode("utf-8")


async def export_workers(session: AsyncSession, month: date) -> ExportResult:
    workers = (await session.execute(select(Worker).order_by(Worker.id))).scalars().all()
    ids = [w.id for w in workers]
    resolved = await resolve_contracts_for_workers(session, ids, month)
    future = await _next_future(session, [i for i in ids if i not in resolved], month)
    rows: list[dict[str, str]] = []
    no_contract = 0
    for w in workers:
        cv = resolved.get(w.id) or future.get(w.id)
        if cv is None:
            no_contract += 1
        rows.append(
            {
                "national_id": _safe(w.national_id),
                "full_name": escape_name(w.full_name),
                "role": _safe(w.role),
                "status": _safe(w.status),
                "effective_month": _safe(f"{cv.effective_month:%Y-%m}") if cv else "",
                "hourly_rate_ils": _safe(f"{cv.hourly_rate_ils:.2f}") if cv else "",
                "min_monthly_hours": _safe(str(cv.min_hours)) if cv else "",
                "max_monthly_hours": _safe(str(cv.max_hours)) if cv else "",
                "availability": _safe(per_day_form(cv.availability)) if cv else "",
                "export_format": EXPORT_FORMAT,
            }
        )
    return ExportResult(render_csv(rows), len(workers), no_contract)
