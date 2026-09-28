"""§4.8 Seeded benchmark fixtures: small (named scenarios) and scale
(200/500/1000 active workers). Pure; only imports the engine + stdlib."""
from __future__ import annotations

import random
from datetime import date

from app.scheduling.types import (
    DEFAULT_DEMAND, Assignment, Problem, Role, Shift, Weekday, WorkerInput,
)

FULL_AVAILABILITY = frozenset((wd, s) for wd in Weekday for s in Shift)
ROLE_MIX = (Role.GENERAL_GUARD, Role.GENERAL_GUARD, Role.SCREENER, Role.SCREENER, Role.SUPERVISOR)  # matches 2:2:1


def _availability(rng: random.Random, fraction: float) -> frozenset:
    all_pairs = [(wd, s) for wd in Weekday for s in Shift]
    if fraction >= 1.0:
        return frozenset(all_pairs)
    k = max(1, int(len(all_pairs) * fraction))
    return frozenset(rng.sample(all_pairs, k))


def make_workers(rng: random.Random, n: int, *, min_hours=0, max_hours=180,
                  availability_fraction=1.0, inactive_fraction=0.0) -> list[WorkerInput]:
    workers = []
    for i in range(n):
        role = ROLE_MIX[i % len(ROLE_MIX)]
        active = rng.random() >= inactive_fraction
        workers.append(WorkerInput(
            id=f"w{i}", role=role, active=active,
            availability=_availability(rng, availability_fraction),
            min_hours=min_hours, max_hours=max_hours,
        ))
    return workers


def comfortable(year=2026, month=10, seed=1) -> Problem:  # October: 31-day month
    rng = random.Random(seed)
    workers = make_workers(rng, 40, min_hours=100, max_hours=180)
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=(date(year, month, 1), Shift.A))


def tight(year=2026, month=10, seed=2) -> Problem:  # October: 31-day month
    """Capacity approx demand: 15 slots/day * ~8 shifts/worker/month needed ~
    just enough workers to (barely) cover demand."""
    rng = random.Random(seed)
    # 15 slots/day, each worker can do ~8 shifts (max_hours=64 -> 8 shifts) in the month
    workers = make_workers(rng, 20, min_hours=0, max_hours=64)
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=(date(year, month, 1), Shift.A))


def short_supervisors(year=2026, month=11, seed=3) -> Problem:
    rng = random.Random(seed)
    workers = make_workers(rng, 40, min_hours=0, max_hours=180)
    # drop all but one supervisor
    supervisors = [w for w in workers if w.role is Role.SUPERVISOR]
    keep = {supervisors[0].id}
    workers = [w for w in workers if w.role is not Role.SUPERVISOR or w.id in keep]
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=(date(year, month, 1), Shift.A))


def fragmented(year=2026, month=11, seed=4) -> Problem:
    rng = random.Random(seed)
    workers = make_workers(rng, 60, min_hours=0, max_hours=180, availability_fraction=0.25)
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=(date(year, month, 1), Shift.A))


def min_hours_pressure(year=2026, month=11, seed=5) -> Problem:
    rng = random.Random(seed)
    workers = make_workers(rng, 40, min_hours=170, max_hours=180)
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=(date(year, month, 1), Shift.A))


def with_inactive_workers(year=2026, month=11, seed=6) -> Problem:
    rng = random.Random(seed)
    workers = make_workers(rng, 50, min_hours=80, max_hours=180, inactive_fraction=0.2)
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=(date(year, month, 1), Shift.A))


def mid_month(year=2026, month=11, seed=7) -> Problem:
    rng = random.Random(seed)
    workers = make_workers(rng, 40, min_hours=80, max_hours=180)
    free_from = (date(year, month, 15), Shift.B)
    fixed = []
    for d in range(1, 15):
        for i, w in enumerate(workers[:5]):
            fixed.append(Assignment(w.id, date(year, month, d), Shift.A, w.role))
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=free_from, fixed_assignments=tuple(fixed))


def retroactive_conflict(year=2026, month=11, seed=8) -> Problem:
    rng = random.Random(seed)
    workers = make_workers(rng, 40, min_hours=0, max_hours=64)  # max lowered below what fixed will use
    free_from = (date(year, month, 10), Shift.A)
    w = workers[0]
    fixed = tuple(Assignment(w.id, date(year, month, d), Shift.A, w.role) for d in range(1, 10))  # 72h > 64h cap
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=free_from, fixed_assignments=fixed)


def neighbor_months(year=2026, month=11, seed=9) -> Problem:
    rng = random.Random(seed)
    workers = make_workers(rng, 40, min_hours=80, max_hours=180)
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    import calendar
    prev_last = date(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1])
    next_first = date(next_year, next_month, 1)
    neighbor = (
        Assignment(workers[0].id, prev_last, Shift.C, workers[0].role),
        Assignment(workers[1].id, next_first, Shift.A, workers[1].role),
    )
    return Problem(year=year, month=month, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=(date(year, month, 1), Shift.A), neighbor_assignments=neighbor,
                   forbid_adjacent_shifts=True)


SMALL_FIXTURES = {
    "comfortable": comfortable,
    "tight": tight,
    "short_supervisors": short_supervisors,
    "fragmented": fragmented,
    "min_hours_pressure": min_hours_pressure,
    "with_inactive_workers": with_inactive_workers,
    "mid_month": mid_month,
    "retroactive_conflict": retroactive_conflict,
    "neighbor_months": neighbor_months,
}


def scale_fixture(n: int, *, comfortable_ratio: bool, mid_month: bool = False, seed=100, year=2026, month=10) -> Problem:
    """n active workers, 31-day month. comfortable_ratio scales demand by k
    to match the comfortable fixture's staffing ratio (40 workers / DEFAULT_DEMAND);
    otherwise demand stays at DEFAULT_DEMAND regardless of n."""
    rng = random.Random(seed)
    workers = make_workers(rng, n, min_hours=100, max_hours=180)
    if comfortable_ratio:
        k = max(1, round(n / 40))
        demand = {key: value * k for key, value in DEFAULT_DEMAND.items()}
    else:
        demand = DEFAULT_DEMAND
    free_from = (date(year, month, 15), Shift.B) if mid_month else (date(year, month, 1), Shift.A)
    fixed = ()
    if mid_month:
        fixed = tuple(Assignment(workers[i % len(workers)].id, date(year, month, d), Shift.A,
                                  workers[i % len(workers)].role)
                      for d in range(1, 15) for i in range(min(5, len(workers))))
    return Problem(year=year, month=month, demand=demand, workers=workers, free_from=free_from,
                   fixed_assignments=fixed)
