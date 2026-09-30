from datetime import date

import pytest

from app.scheduling import Shift, Weekday, WorkerInput

FULL_AVAILABILITY = frozenset((wd, s) for wd in Weekday for s in Shift)


def make_worker(worker_id, role, min_hours=0, max_hours=160, active=True, availability=FULL_AVAILABILITY):
    return WorkerInput(id=worker_id, role=role, active=active, availability=availability,
                        min_hours=min_hours, max_hours=max_hours)


@pytest.fixture
def full_availability():
    return FULL_AVAILABILITY


@pytest.fixture
def november():
    # 2026-11 has 30 days; free_from = whole month free by default.
    return 2026, 11, (date(2026, 11, 1), Shift.A)
