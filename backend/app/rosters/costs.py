"""Estimated costs (P15): 8h x the worker's resolved hourly rate, per
shift/per worker/monthly. `Decimal` throughout; rounding to 0.01 happens
only when a figure is produced for display. Workers with no applicable
contract are "cost unknown" and excluded from totals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.contracts.models import ContractVersion
from app.scheduling.types import Assignment, Shift

HOURS_PER_SHIFT = 8
_CENTS = Decimal("0.01")


def _display(amount: Decimal) -> Decimal:
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass
class WorkerCost:
    worker_id: str
    hours: int
    amount_ils: Decimal | None  # None = "cost unknown" (P15)


@dataclass
class ShiftCost:
    date: date
    shift: Shift
    amount_ils: Decimal
    unknown_cost_assignments: int


@dataclass
class Costs:
    per_worker: list[WorkerCost]
    monthly_total_ils: Decimal
    unknown_cost_worker_count: int
    per_shift: list[ShiftCost]


def compute_costs(assignments: list[Assignment], contract_by_worker_id: dict[int, ContractVersion]) -> Costs:
    hours: dict[str, int] = {}
    shift_exact: dict[tuple[date, Shift], Decimal] = {}
    shift_unknown: dict[tuple[date, Shift], int] = {}
    for a in assignments:
        hours[a.worker_id] = hours.get(a.worker_id, 0) + HOURS_PER_SHIFT
        key = (a.date, a.shift)
        contract = contract_by_worker_id.get(int(a.worker_id))
        shift_exact.setdefault(key, Decimal(0))
        shift_unknown.setdefault(key, 0)
        if contract is None:
            shift_unknown[key] += 1
        else:
            shift_exact[key] += Decimal(HOURS_PER_SHIFT) * contract.hourly_rate_ils

    per_worker: list[WorkerCost] = []
    total = Decimal(0)
    unknown_count = 0
    for worker_id, h in sorted(hours.items(), key=lambda kv: int(kv[0])):
        contract = contract_by_worker_id.get(int(worker_id))
        if contract is None:
            per_worker.append(WorkerCost(worker_id, h, None))
            unknown_count += 1
            continue
        exact = Decimal(h) * contract.hourly_rate_ils
        per_worker.append(WorkerCost(worker_id, h, _display(exact)))
        total += exact

    per_shift = [
        ShiftCost(d, s, _display(shift_exact[(d, s)]), shift_unknown[(d, s)])
        for (d, s) in sorted(shift_exact, key=lambda k: (k[0], k[1].value))
    ]
    return Costs(per_worker, _display(total), unknown_count, per_shift)
