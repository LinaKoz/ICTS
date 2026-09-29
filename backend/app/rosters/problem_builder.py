"""Builds a `scheduling.types.Problem` for a given month (§4.2, §6, T3).

Resolves `free_from` from `now_israel()`, loads stored assignments of
already-started shifts as `fixed_assignments`, loads neighbor-month
boundary assignments only where the adjacency rule applies, and
excludes inactive workers' capacity and workers with no applicable
contract (P4) from the engine's search -- while still handing the
engine enough to validate existing (fixed) assignments correctly
(§4.3, D9(b)).
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.models import ContractVersion
from app.errors import BadRequestError
from app.contracts.resolve import resolve_contracts_for_workers
from app.rosters.models import Roster, RosterAssignment
from app.scheduling.types import DEFAULT_DEMAND, Assignment, Problem, Role, Shift, Weekday, WorkerInput
from app.timeutil import now_israel, shift_start_time
from app.workers.models import Worker

_SHIFT_ORDER = {Shift.A: 0, Shift.B: 1, Shift.C: 2}
_WEEKDAYS = tuple(Weekday)  # MON..SUN, matches date.weekday() 0..6
_ALL_AVAILABILITY = frozenset((d, s) for d in Weekday for s in Shift)
_MAX_MONTH_HOURS = 744


MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
_MONTH_RE = re.compile(MONTH_PATTERN)


def parse_month(month_str: str) -> date:
    """Parses a strict `YYYY-MM` path parameter into the month's first day.

    Raises `BadRequestError` (400) for anything else, so a hand-typed
    URL never reaches the database or turns into a 500.
    """
    if not _MONTH_RE.fullmatch(month_str):
        raise BadRequestError(f"invalid month {month_str!r}, expected YYYY-MM")
    return date(int(month_str[:4]), int(month_str[5:7]), 1)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day_num = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day_num)


def _month_days(year: int, month: int) -> list[date]:
    first, last = _month_bounds(year, month)
    return [date.fromordinal(first.toordinal() + i) for i in range((last - first).days + 1)]


def _pos(d: date, s: Shift) -> tuple[date, int]:
    return (d, _SHIFT_ORDER[s])


def _adjacent_month(month: date, delta: int) -> date:
    y, m = month.year, month.month + delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, 1)


def is_history_month(month: date, now: datetime | None = None) -> bool:
    """§3 P3: a month strictly before the current Israel month is
    read-only history."""
    now = now or now_israel()
    return (month.year, month.month) < (now.year, now.month)


def compute_free_from(month: date, now: datetime | None = None) -> tuple[date, Shift]:
    """§4.1 "Locked and free shifts": the first shift whose start is
    after `now_israel()`, for the current month; `(1st, A)` for a
    future month; `(last day + 1, A)` for a fully-locked past month."""
    now = now or now_israel()
    first, last = _month_bounds(month.year, month.month)
    current_month_first = date(now.year, now.month, 1)
    if first > current_month_first:
        return (first, Shift.A)
    after_last = date.fromordinal(last.toordinal() + 1)
    if first < current_month_first:
        return (after_last, Shift.A)
    for d in _month_days(month.year, month.month):
        for s in (Shift.A, Shift.B, Shift.C):
            if shift_start_time(d, s) > now:
                return (d, s)
    return (after_last, Shift.A)


@dataclass
class BuiltProblem:
    problem: Problem
    roster: Roster | None
    prev_roster: Roster | None
    next_roster: Roster | None
    no_contract_worker_ids: list[int] = field(default_factory=list)
    contract_by_worker_id: dict[int, ContractVersion] = field(default_factory=dict)


async def _load_roster(session: AsyncSession, month: date) -> Roster | None:
    stmt = select(Roster).where(Roster.month == month)
    return (await session.execute(stmt)).scalar_one_or_none()


def _parse_availability(raw: list[str]) -> frozenset[tuple[Weekday, Shift]]:
    out = set()
    for token in raw:
        day, shift = token.split(":")
        out.add((Weekday(day), Shift(shift)))
    return frozenset(out)


async def build_problem(
    session: AsyncSession,
    month: date,
    forbid_adjacent_shifts: bool,
    now: datetime | None = None,
) -> BuiltProblem:
    now = now or now_israel()
    roster = await _load_roster(session, month)
    prev_roster = await _load_roster(session, _adjacent_month(month, -1))
    next_roster = await _load_roster(session, _adjacent_month(month, 1))

    free_from = compute_free_from(month, now)

    workers = (await session.execute(select(Worker))).scalars().all()
    # Contracts are resolved for every worker: inactive workers with a
    # contract keep their real availability/hours (so their locked
    # assignments are not flagged UNAVAILABLE/MAX_HOURS after a later
    # deactivation, D9(b)) and their cost stays known (P15).
    contract_by_worker_id = await resolve_contracts_for_workers(session, [w.id for w in workers], month)

    worker_inputs: list[WorkerInput] = []
    no_contract_worker_ids: list[int] = []
    for w in workers:
        if w.status == "ACTIVE":
            contract = contract_by_worker_id.get(w.id)
            if contract is None:
                no_contract_worker_ids.append(w.id)
                continue  # excluded entirely (P4, C3): engine reports UNKNOWN_WORKER
            worker_inputs.append(
                WorkerInput(
                    id=str(w.id),
                    role=Role(w.role),
                    active=True,
                    availability=_parse_availability(contract.availability),
                    min_hours=contract.min_hours,
                    max_hours=contract.max_hours,
                )
            )
        else:
            # Inactive: included so the validator reports INACTIVE_WORKER
            # (not UNKNOWN_WORKER) for their fixed assignments (§4.3). The
            # engine never builds variables or capacity for them. Without a
            # contract, availability is wide open so only INACTIVE_WORKER
            # (never UNAVAILABLE/MAX_HOURS noise) can be reported.
            contract = contract_by_worker_id.get(w.id)
            worker_inputs.append(
                WorkerInput(
                    id=str(w.id),
                    role=Role(w.role),
                    active=False,
                    availability=_parse_availability(contract.availability) if contract else _ALL_AVAILABILITY,
                    min_hours=0,
                    max_hours=contract.max_hours if contract else _MAX_MONTH_HOURS,
                )
            )

    fixed_assignments: list[Assignment] = []
    if roster is not None:
        stmt = select(RosterAssignment).where(RosterAssignment.roster_id == roster.id)
        for ra in (await session.execute(stmt)).scalars():
            if _pos(ra.date, Shift(ra.shift)) < _pos(*free_from):
                fixed_assignments.append(Assignment(str(ra.worker_id), ra.date, Shift(ra.shift), Role(ra.role)))

    neighbor_assignments: list[Assignment] = []
    first, last = _month_bounds(month.year, month.month)
    if prev_roster is not None and (forbid_adjacent_shifts or prev_roster.forbid_adjacent_shifts):
        prev_last_day = date.fromordinal(first.toordinal() - 1)
        stmt = select(RosterAssignment).where(
            RosterAssignment.roster_id == prev_roster.id, RosterAssignment.date == prev_last_day
        )
        for ra in (await session.execute(stmt)).scalars():
            neighbor_assignments.append(Assignment(str(ra.worker_id), ra.date, Shift(ra.shift), Role(ra.role)))
    if next_roster is not None and (forbid_adjacent_shifts or next_roster.forbid_adjacent_shifts):
        next_first_day = date.fromordinal(last.toordinal() + 1)
        stmt = select(RosterAssignment).where(
            RosterAssignment.roster_id == next_roster.id, RosterAssignment.date == next_first_day
        )
        for ra in (await session.execute(stmt)).scalars():
            neighbor_assignments.append(Assignment(str(ra.worker_id), ra.date, Shift(ra.shift), Role(ra.role)))

    problem = Problem(
        year=month.year,
        month=month.month,
        demand=DEFAULT_DEMAND,
        workers=worker_inputs,
        free_from=free_from,
        fixed_assignments=tuple(fixed_assignments),
        neighbor_assignments=tuple(neighbor_assignments),
        forbid_adjacent_shifts=forbid_adjacent_shifts,
    )
    return BuiltProblem(
        problem=problem,
        roster=roster,
        prev_roster=prev_roster,
        next_roster=next_roster,
        no_contract_worker_ids=no_contract_worker_ids,
        contract_by_worker_id=contract_by_worker_id,
    )


async def compute_fingerprint(session: AsyncSession, built: BuiltProblem) -> str:
    """§6 "save": a hash of the worker ids and their row versions, the
    resolved contract ids, the demand, the roster version, `free_from`,
    `forbid_adjacent_shifts`, and the neighbor rosters' versions and
    flags."""
    workers = (await session.execute(select(Worker.id, Worker.row_version).order_by(Worker.id))).all()
    payload = {
        "workers": [[wid, rv] for wid, rv in workers],
        "contracts": sorted((wid, cv.id) for wid, cv in built.contract_by_worker_id.items()),
        "demand": sorted((s.value, r.value, n) for (s, r), n in DEFAULT_DEMAND.items()),
        "roster_version": built.roster.row_version if built.roster else 0,
        "free_from": [built.problem.free_from[0].isoformat(), built.problem.free_from[1].value],
        "forbid_adjacent_shifts": built.problem.forbid_adjacent_shifts,
        "prev": [built.prev_roster.row_version, built.prev_roster.forbid_adjacent_shifts] if built.prev_roster else None,
        "next": [built.next_roster.row_version, built.next_roster.forbid_adjacent_shifts] if built.next_roster else None,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()
