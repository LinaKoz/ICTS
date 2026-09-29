"""Checks the frozen contract shape (§4.2).

Engine independence (§4.9) and the real behaviour of solve/validate_problem/
validate_roster/roster_metrics/worsened/diagnose are covered by T1's
tests/scheduling/ suite, which supersedes this file's original
not-implemented-stub and import-scan checks now that T1 has implemented them.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.scheduling import types as t


def test_dataclasses_are_frozen():
    for cls in (t.WorkerInput, t.Assignment, t.Violation, t.Problem, t.SolverConfig):
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen is True

    assignment = t.Assignment(worker_id="w1", date=__import__("datetime").date(2026, 1, 1), shift=t.Shift.A, role=t.Role.SCREENER)
    with pytest.raises(dataclasses.FrozenInstanceError):
        assignment.worker_id = "w2"  # type: ignore[misc]


def test_problem_defaults():
    assert t.Problem.__dataclass_fields__["fixed_assignments"].default_factory() == ()
    assert t.Problem.__dataclass_fields__["forbid_adjacent_shifts"].default is False


