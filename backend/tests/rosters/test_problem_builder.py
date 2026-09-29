"""§8 T3 acceptance: problem builder -- inactive, no contract, `free_from`
from a frozen clock (before midnight, mid-shift, exactly at a shift
start), fixed from stored started shifts, neighbor-month assignments
passed only where the adjacency rule applies."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

from tests.conftest import requires_db
from tests.rosters.helpers import insert_assignment, insert_contract, insert_roster, insert_user, insert_worker

TZ = ZoneInfo("Asia/Jerusalem")


def _run(coro):
    return asyncio.run(coro)


# --- free_from, frozen clock ------------------------------------------------


def test_free_from_future_month_is_first_of_month_a():
    from app.rosters.problem_builder import compute_free_from
    from app.scheduling.types import Shift

    now = datetime(2026, 1, 15, 10, 0, tzinfo=TZ)
    assert compute_free_from(date(2026, 3, 1), now) == (date(2026, 3, 1), Shift.A)


def test_free_from_past_month_is_fully_locked():
    from app.rosters.problem_builder import compute_free_from
    from app.scheduling.types import Shift

    now = datetime(2026, 3, 15, 10, 0, tzinfo=TZ)
    assert compute_free_from(date(2026, 1, 1), now) == (date(2026, 2, 1), Shift.A)


def test_free_from_current_month_mid_shift():
    from app.rosters.problem_builder import compute_free_from
    from app.scheduling.types import Shift

    now = datetime(2026, 3, 10, 10, 30, tzinfo=TZ)  # inside shift B on day 10
    assert compute_free_from(date(2026, 3, 1), now) == (date(2026, 3, 10), Shift.C)


def test_free_from_current_month_exactly_at_shift_start_is_locked():
    from app.rosters.problem_builder import compute_free_from
    from app.scheduling.types import Shift

    now = datetime(2026, 3, 10, 8, 0, 0, tzinfo=TZ)  # exactly B's start: B has "started"
    assert compute_free_from(date(2026, 3, 1), now) == (date(2026, 3, 10), Shift.C)


def test_free_from_current_month_before_midnight_rolls_to_next_day():
    from app.rosters.problem_builder import compute_free_from
    from app.scheduling.types import Shift

    now = datetime(2026, 3, 10, 23, 59, 0, tzinfo=TZ)
    assert compute_free_from(date(2026, 3, 1), now) == (date(2026, 3, 11), Shift.A)


# --- inactive / no-contract exclusion, fixed assignments --------------------


@requires_db
def test_build_problem_excludes_no_contract_worker_and_includes_inactive(db):
    import app.models  # noqa: F401
    from app.db import async_session_factory
    from app.rosters.problem_builder import build_problem
    from app.scheduling.types import Role

    user_id = insert_user(db)
    with_contract = insert_worker(db, "111111118", role="GENERAL_GUARD")
    insert_contract(db, with_contract, user_id, effective_month=date(2026, 1, 1))
    no_contract = insert_worker(db, "222222226", role="SCREENER")
    inactive = insert_worker(db, "333333334", role="SUPERVISOR", status="INACTIVE")

    async def run():
        async with async_session_factory() as session:
            return await build_problem(session, date(2026, 3, 1), False, now=datetime(2026, 3, 1, tzinfo=TZ))

    built = _run(run())

    assert no_contract in built.no_contract_worker_ids
    ids = {w.id for w in built.problem.workers}
    assert str(with_contract) in ids
    assert str(no_contract) not in ids  # excluded entirely (P4, C3)
    assert str(inactive) in ids  # included so fixed assignments validate as INACTIVE_WORKER
    inactive_input = next(w for w in built.problem.workers if w.id == str(inactive))
    assert inactive_input.active is False
    assert inactive_input.role is Role.SUPERVISOR


@requires_db
def test_build_problem_loads_started_shifts_as_fixed_assignments(db):
    import app.models  # noqa: F401
    from app.db import async_session_factory
    from app.rosters.problem_builder import build_problem
    from app.scheduling.types import Shift

    user_id = insert_user(db)
    worker_id = insert_worker(db, "111111118")
    insert_contract(db, worker_id, user_id, effective_month=date(2026, 3, 1))
    roster_id = insert_roster(db, date(2026, 3, 1), user_id)
    insert_assignment(db, roster_id, worker_id, date(2026, 3, 5), "A", "GENERAL_GUARD")  # started
    insert_assignment(db, roster_id, worker_id, date(2026, 3, 20), "A", "GENERAL_GUARD")  # future, not fixed

    async def run():
        async with async_session_factory() as session:
            return await build_problem(
                session, date(2026, 3, 1), False, now=datetime(2026, 3, 10, 0, 0, tzinfo=TZ)
            )

    built = _run(run())
    fixed_dates = {(a.date, a.shift) for a in built.problem.fixed_assignments}
    assert (date(2026, 3, 5), Shift.A) in fixed_dates
    assert (date(2026, 3, 20), Shift.A) not in fixed_dates


# --- neighbor-month assignments, adjacency applicability --------------------


@requires_db
def test_neighbor_assignments_loaded_when_this_roster_flag_on(db):
    import app.models  # noqa: F401
    from app.db import async_session_factory
    from app.rosters.problem_builder import build_problem

    user_id = insert_user(db)
    worker_id = insert_worker(db, "111111118")
    insert_contract(db, worker_id, user_id, effective_month=date(2026, 1, 1))
    prev_roster_id = insert_roster(db, date(2026, 2, 1), user_id, forbid_adjacent_shifts=False)
    insert_assignment(db, prev_roster_id, worker_id, date(2026, 2, 28), "C", "GENERAL_GUARD")

    async def run():
        async with async_session_factory() as session:
            # This roster's own flag is on -> boundary applies even though neighbor's is off.
            return await build_problem(session, date(2026, 3, 1), True, now=datetime(2026, 1, 1, tzinfo=TZ))

    built = _run(run())
    assert len(built.problem.neighbor_assignments) == 1
    assert built.problem.neighbor_assignments[0].date == date(2026, 2, 28)


@requires_db
def test_neighbor_assignments_loaded_when_neighbor_flag_on(db):
    import app.models  # noqa: F401
    from app.db import async_session_factory
    from app.rosters.problem_builder import build_problem

    user_id = insert_user(db)
    worker_id = insert_worker(db, "111111118")
    insert_contract(db, worker_id, user_id, effective_month=date(2026, 1, 1))
    prev_roster_id = insert_roster(db, date(2026, 2, 1), user_id, forbid_adjacent_shifts=True)
    insert_assignment(db, prev_roster_id, worker_id, date(2026, 2, 28), "C", "GENERAL_GUARD")

    async def run():
        async with async_session_factory() as session:
            # This roster's flag is off, but the neighbor's is on -> boundary still applies.
            return await build_problem(session, date(2026, 3, 1), False, now=datetime(2026, 1, 1, tzinfo=TZ))

    built = _run(run())
    assert len(built.problem.neighbor_assignments) == 1


@requires_db
def test_neighbor_assignments_absent_when_neither_flag_on(db):
    import app.models  # noqa: F401
    from app.db import async_session_factory
    from app.rosters.problem_builder import build_problem

    user_id = insert_user(db)
    worker_id = insert_worker(db, "111111118")
    insert_contract(db, worker_id, user_id, effective_month=date(2026, 1, 1))
    prev_roster_id = insert_roster(db, date(2026, 2, 1), user_id, forbid_adjacent_shifts=False)
    insert_assignment(db, prev_roster_id, worker_id, date(2026, 2, 28), "C", "GENERAL_GUARD")

    async def run():
        async with async_session_factory() as session:
            return await build_problem(session, date(2026, 3, 1), False, now=datetime(2026, 1, 1, tzinfo=TZ))

    built = _run(run())
    assert built.problem.neighbor_assignments == ()


def _build(month, flag, now=datetime(2026, 1, 1, tzinfo=TZ)):
    import app.models  # noqa: F401
    from app.db import async_session_factory
    from app.rosters.problem_builder import build_problem

    async def run():
        async with async_session_factory() as session:
            return await build_problem(session, month, flag, now=now)

    return _run(run())


@requires_db
def test_neighbor_next_month_boundary_only_first_day_and_only_where_rule_applies(db):
    user_id = insert_user(db)
    worker_id = insert_worker(db, "111111118")
    insert_contract(db, worker_id, user_id, effective_month=date(2026, 1, 1))
    nxt = insert_roster(db, date(2026, 4, 1), user_id, forbid_adjacent_shifts=True)
    insert_assignment(db, nxt, worker_id, date(2026, 4, 1), "A", "GENERAL_GUARD")
    insert_assignment(db, nxt, worker_id, date(2026, 4, 2), "A", "GENERAL_GUARD")  # not a boundary day

    built = _build(date(2026, 3, 1), False)  # neighbor's flag on
    assert [(a.date, a.shift.value) for a in built.problem.neighbor_assignments] == [(date(2026, 4, 1), "A")]

    with db.cursor() as cur:
        cur.execute("UPDATE rosters SET forbid_adjacent_shifts = false WHERE id = %s", (nxt,))
    assert _build(date(2026, 3, 1), False).problem.neighbor_assignments == ()  # neither
    assert len(_build(date(2026, 3, 1), True).problem.neighbor_assignments) == 1  # this roster's flag


@requires_db
def test_neighbor_month_across_year_boundary(db):
    user_id = insert_user(db)
    worker_id = insert_worker(db, "111111118")
    insert_contract(db, worker_id, user_id, effective_month=date(2026, 1, 1))
    prev = insert_roster(db, date(2026, 12, 1), user_id, forbid_adjacent_shifts=True)
    insert_assignment(db, prev, worker_id, date(2026, 12, 31), "C", "GENERAL_GUARD")
    built = _build(date(2027, 1, 1), False)
    assert [a.date for a in built.problem.neighbor_assignments] == [date(2026, 12, 31)]


@requires_db
def test_inactive_worker_with_contract_keeps_availability_and_hours(db):
    user_id = insert_user(db)
    inactive = insert_worker(db, "333333334", status="INACTIVE")
    insert_contract(db, inactive, user_id, effective_month=date(2026, 1, 1), max_hours=96, availability=["MON:A"])
    built = _build(date(2026, 3, 1), False)
    w = built.problem.workers[0]
    assert w.active is False and w.max_hours == 96 and len(w.availability) == 1
    assert built.contract_by_worker_id[inactive].max_hours == 96


@requires_db
def test_build_problem_resolves_contract_for_the_roster_month(db):
    user_id = insert_user(db)
    w = insert_worker(db, "111111118")
    insert_contract(db, w, user_id, version_no=1, effective_month=date(2026, 1, 1), max_hours=100)
    insert_contract(db, w, user_id, version_no=2, effective_month=date(2026, 4, 1), max_hours=150)
    assert _build(date(2026, 3, 1), False).problem.workers[0].max_hours == 100
    assert _build(date(2026, 4, 1), False).problem.workers[0].max_hours == 150
    assert _build(date(2026, 5, 1), False).problem.workers[0].max_hours == 150
    assert [x.id for x in _build(date(2025, 12, 1), False).problem.workers] == []  # before first version


@requires_db
def test_fingerprint_changes_with_inputs(db):
    from app.db import async_session_factory
    from app.rosters.problem_builder import build_problem, compute_fingerprint

    user_id = insert_user(db)
    w = insert_worker(db, "111111118")
    insert_contract(db, w, user_id, effective_month=date(2026, 1, 1))

    def fp(month=date(2026, 3, 1), flag=False, now=datetime(2026, 1, 1, tzinfo=TZ)):
        async def run():
            async with async_session_factory() as session:
                return await compute_fingerprint(session, await build_problem(session, month, flag, now=now))
        return _run(run())

    base = fp()
    assert fp() == base  # deterministic
    assert fp(flag=True) != base
    assert fp(now=datetime(2026, 3, 10, 12, tzinfo=TZ)) != base  # free_from moved
    insert_roster(db, date(2026, 3, 1), user_id)
    assert fp() != base  # roster version 0 -> 1
