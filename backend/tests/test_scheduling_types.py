"""Checks the frozen contract shape (§4.2) and engine independence (§4.9)."""
from __future__ import annotations

import ast
import dataclasses
import pathlib

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


def test_stub_functions_raise_not_implemented():
    with pytest.raises(NotImplementedError):
        t.validate_problem(None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        t.diagnose(None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        t.roster_metrics(None, None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        t.solve(None, None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        t.validate_roster(None, None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        t.worsened(None, None)  # type: ignore[arg-type]


def test_engine_does_not_import_outside_scheduling_or_stdlib():
    """The engine is pure Python on CP-SAT (§4): no sqlalchemy, no
    fastapi, no other app.* module outside scheduling."""
    scheduling_dir = pathlib.Path(t.__file__).resolve().parent
    forbidden_roots = {"sqlalchemy", "fastapi", "psycopg", "alembic"}
    for py_file in scheduling_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root not in forbidden_roots, f"{py_file}: forbidden import {name}"
                if root == "app":
                    assert name == "app.scheduling" or name.startswith("app.scheduling."), (
                        f"{py_file}: engine must not import outside app.scheduling ({name})"
                    )
