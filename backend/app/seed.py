"""Idempotent startup seed (§2, §8 T2).

Creates the demo users (`planner`/`manager`, passwords from
`PLANNER_PASSWORD`/`MANAGER_PASSWORD`) if missing — it never overwrites
an existing user's password. If `workers` is empty, it also loads a
small placeholder sample of workers and one contract version each (plus
25 demo workers unless `SEED_DEMO_WORKERS=false`), so the vertical slice
works on first start. A populated `workers` table is never touched. The real sample CSV is T6's
job; this seed never reads a CSV file, so it cannot fail if one is
missing yet.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import hash_password
from app.config import settings
from app.timeutil import now_israel
from app.contracts.models import ContractVersion
from app.workers.models import Worker
from app.workers.national_id import israeli_id_checksum_ok

_DEMO_USERS = (
    ("planner", "Planner", settings.planner_password, "PLANNER"),
    ("manager", "Manager", settings.manager_password, "MANAGER"),
)

# Placeholder sample only (§8 T2); the real sample-data/workers.csv is T6's.
_SAMPLE_WORKERS = (
    # national_id, full_name, role
    ("111111118", "Alice Guard", "GENERAL_GUARD"),
    ("222222226", "Ben Guard", "GENERAL_GUARD"),
    ("333333334", "Cara Screener", "SCREENER"),
    ("444444442", "Dana Screener", "SCREENER"),
    ("555555556", "Eli Supervisor", "SUPERVISOR"),
)
_SAMPLE_HOURLY_RATE = Decimal("45.00")
_SAMPLE_MIN_HOURS = 0
_SAMPLE_MAX_HOURS = 186  # about 3 shifts/week * 8h * ~7.7 weeks headroom
_SAMPLE_AVAILABILITY = [
    f"{day}:{shift}"
    for day in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    for shift in ("A", "B", "C")
]

# 25 extra workers: 200h/month cap, 50 ILS/hour. Roles are mixed.
_EXTRA_ROLES = ("GENERAL_GUARD",) * 12 + ("SCREENER",) * 6 + ("SUPERVISOR",) * 7
_EXTRA_HOURLY_RATE = Decimal("50.00")
_EXTRA_MAX_HOURS = 200


def _extra_national_id(n: int) -> str:
    """Deterministic valid 9-digit ID: `9000` + 4-digit n + check digit."""
    prefix = f"9000{n:04d}"
    return next(prefix + str(d) for d in range(10) if israeli_id_checksum_ok(prefix + str(d)))


_EXTRA_WORKERS = tuple(
    (_extra_national_id(i), f"Worker {i:02d}", role) for i, role in enumerate(_EXTRA_ROLES, start=1)
)


async def seed(session: AsyncSession) -> None:
    planner_id = await _ensure_user(session, *_DEMO_USERS[0])
    await _ensure_user(session, *_DEMO_USERS[1])

    # Decided once, before any insert: workers are seeded only into an empty
    # table, so a restart never re-adds a deleted worker or touches an edited one.
    worker_count = (await session.execute(select(func.count()).select_from(Worker))).scalar_one()
    if worker_count == 0:
        effective_month = now_israel().date().replace(day=1)
        await _add_workers(session, _SAMPLE_WORKERS, _SAMPLE_HOURLY_RATE, _SAMPLE_MAX_HOURS, effective_month, planner_id)
        if settings.seed_demo_workers:
            await _add_workers(session, _EXTRA_WORKERS, _EXTRA_HOURLY_RATE, _EXTRA_MAX_HOURS, effective_month, planner_id)
    await session.commit()


async def _add_workers(
    session: AsyncSession,
    workers: tuple[tuple[str, str, str], ...],
    hourly_rate: Decimal,
    max_hours: int,
    effective_month: date,
    planner_id: int,
) -> None:
    for national_id, full_name, role in workers:
        worker = Worker(national_id=national_id, full_name=full_name, role=role, status="ACTIVE")
        session.add(worker)
        await session.flush()  # assigns worker.id
        session.add(
            ContractVersion(
                worker_id=worker.id,
                version_no=1,
                effective_month=effective_month,
                hourly_rate_ils=hourly_rate,
                min_hours=_SAMPLE_MIN_HOURS,
                max_hours=max_hours,
                availability=_SAMPLE_AVAILABILITY,
                created_by=planner_id,
                source="UI",
            )
        )


async def _ensure_user(session: AsyncSession, username: str, display_name: str, password: str, app_role: str) -> int:
    existing = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if existing is not None:
        return existing.id
    user = User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        app_role=app_role,
    )
    session.add(user)
    await session.flush()  # assigns user.id
    return user.id
