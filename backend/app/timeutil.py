"""One helper, `now_israel()` (§2 "Time"): decides the current month and
which shifts have started. The container clock is UTC; this module is
the only place that knows the timezone.

Small and shared across `rosters/*` (problem_builder, evaluation) and,
later, CSV import's `effective_month` default (P14/D11). Kept outside
`app/rosters` because it has no roster-specific knowledge.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

_SHIFT_START_HOUR = {"A": 0, "B": 8, "C": 16}


def now_israel() -> datetime:
    """The current time in Asia/Jerusalem."""
    return datetime.now(ISRAEL_TZ)


def shift_start_time(d: date, shift: str) -> datetime:
    """The Israel-local start time of shift `shift` (A/B/C) on date `d`."""
    return datetime.combine(d, time(hour=_SHIFT_START_HOUR[shift]), tzinfo=ISRAEL_TZ)


def next_day(d: date) -> date:
    return d + timedelta(days=1)
