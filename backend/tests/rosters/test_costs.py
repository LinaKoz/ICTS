"""§8 T3: costs -- per shift/worker/month, missing contract counted as
unknown, `Decimal` rounding (P15)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.rosters.costs import compute_costs
from app.scheduling import Assignment, Role, Shift


def _a(worker: int, d: int, shift: Shift) -> Assignment:
    return Assignment(str(worker), date(2026, 3, d), shift, Role.GENERAL_GUARD)


def _contract(rate: str) -> SimpleNamespace:
    return SimpleNamespace(hourly_rate_ils=Decimal(rate))


def test_costs_per_worker_shift_and_month_total():
    contracts = {1: _contract("40.00"), 2: _contract("55.50")}
    assignments = [_a(1, 1, Shift.A), _a(2, 1, Shift.A), _a(1, 2, Shift.B)]
    costs = compute_costs(assignments, contracts)

    per_worker = {wc.worker_id: wc for wc in costs.per_worker}
    assert per_worker["1"].hours == 16 and per_worker["1"].amount_ils == Decimal("640.00")
    assert per_worker["2"].hours == 8 and per_worker["2"].amount_ils == Decimal("444.00")
    assert costs.monthly_total_ils == Decimal("1084.00")
    shifts = {(sc.date, sc.shift): sc for sc in costs.per_shift}
    assert shifts[(date(2026, 3, 1), Shift.A)].amount_ils == Decimal("764.00")
    assert shifts[(date(2026, 3, 2), Shift.B)].amount_ils == Decimal("320.00")
    assert costs.unknown_cost_worker_count == 0


def test_costs_missing_contract_is_unknown_and_excluded_from_totals():
    costs = compute_costs([_a(1, 1, Shift.A), _a(9, 1, Shift.A)], {1: _contract("40.00")})
    per_worker = {wc.worker_id: wc for wc in costs.per_worker}
    assert per_worker["9"].amount_ils is None
    assert costs.unknown_cost_worker_count == 1
    assert costs.monthly_total_ils == Decimal("320.00")
    (shift_cost,) = costs.per_shift
    assert shift_cost.amount_ils == Decimal("320.00") and shift_cost.unknown_cost_assignments == 1


def test_costs_decimal_exact_no_float_drift():
    # 0.1 + 0.2 style drift would show up with floats; Decimal rates stay exact.
    contracts = {1: _contract("33.33"), 2: _contract("0.01")}
    costs = compute_costs([_a(1, d, Shift.A) for d in range(1, 4)] + [_a(2, 1, Shift.B)], contracts)
    assert costs.monthly_total_ils == Decimal("799.92") + Decimal("0.08")
    assert isinstance(costs.monthly_total_ils, Decimal)


def test_costs_rounding_half_up_to_cents_on_display_only():
    # 8h x 0.125 (a sub-cent rate) = 1.000 exactly; 3 x 0.0625... use a rate with 3 decimals
    contracts = {1: _contract("10.0625")}  # 8h -> 80.50; 16h -> 161.00 (exact)
    costs = compute_costs([_a(1, 1, Shift.A)], contracts)
    assert costs.per_worker[0].amount_ils == Decimal("80.50")
    contracts = {1: _contract("0.00125")}  # 8h -> 0.01 exactly; 16h -> 0.02
    one = compute_costs([_a(1, 1, Shift.A)], contracts)
    assert one.monthly_total_ils == Decimal("0.01")
    # Two workers each 0.004 (rounds to 0.00 each) sum to 0.008 -> 0.01: rounding happens once, at the end.
    contracts = {1: _contract("0.0005"), 2: _contract("0.0005")}
    both = compute_costs([_a(1, 1, Shift.A), _a(2, 1, Shift.A)], contracts)
    assert [wc.amount_ils for wc in both.per_worker] == [Decimal("0.00"), Decimal("0.00")]
    assert both.monthly_total_ils == Decimal("0.01")
