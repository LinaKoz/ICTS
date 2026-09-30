"""§4.9 Solver fixtures (hand-computed optima)."""
import itertools
from datetime import date

from app.scheduling import (
    Assignment, Problem, Role, Shift, SolverConfig, Solved, Weekday, solve,
)
from tests.scheduling.conftest import make_worker

YEAR, MONTH = 2026, 11
FF = (date(YEAR, MONTH, 1), Shift.A)
CFG = SolverConfig(time_limit_s=10.0)


def test_fully_coverable_zero_gaps_lexicographically_optimal():
    workers = ([make_worker(f"g{i}", Role.GENERAL_GUARD, max_hours=744) for i in range(2)]
               + [make_worker(f"s{i}", Role.SCREENER, max_hours=744) for i in range(2)]
               + [make_worker("sv", Role.SUPERVISOR, max_hours=744)])
    demand = {(Shift.A, Role.GENERAL_GUARD): 2, (Shift.A, Role.SCREENER): 2, (Shift.A, Role.SUPERVISOR): 1}
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=workers, free_from=FF)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert result.coverage.total_uncovered == 0
    assert result.lexicographically_optimal is True
    assert result.coverage.status == "OPTIMAL"


def test_one_supervisor_three_shift_demand_both_modes():
    """Demand: 1 SUPERVISOR per shift (A,B,C) every day = 3/day, one supervisor.
    Rule off: at most 2 shifts/day (daily limit, any 2), independent per day,
    so the gap is exactly 1/day = 30 for a 30-day November, proven tight.
    Rule on: the day_cap of 2 (A+C) is still an upper bound per day, but a
    day's C shift blocks the next day's A (cross-day adjacency, always
    enforced), so achievable coverage is lower still; whatever CP-SAT proves
    OPTIMAL is reported as an exact (proven) gap either way.
    """
    demand = {(Shift.A, Role.SUPERVISOR): 1, (Shift.B, Role.SUPERVISOR): 1, (Shift.C, Role.SUPERVISOR): 1}
    results = {}
    for rule in (False, True):
        worker = make_worker("sv", Role.SUPERVISOR, min_hours=0, max_hours=744)
        p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=FF,
                    forbid_adjacent_shifts=rule)
        result = solve(p, CFG)
        assert isinstance(result, Solved), result
        assert result.coverage.status == "OPTIMAL"
        assert result.coverage.lower_bound == result.coverage.total_uncovered  # proven tight
        results[rule] = result.coverage.total_uncovered
    assert results[False] == 30  # demand(3/day) - daily_limit(2/day), independent per day
    assert results[True] >= results[False]  # cross-day adjacency can only cost more coverage


def test_adjacency_rule_on_leaves_gap_rule_off_fully_covered():
    """Demand: A=1, B=1/day, one worker eligible for both. Rule on forbids A+B
    (adjacent) so at most one is filled -> gap. Rule off allows both -> full
    coverage using back-to-back shifts."""
    demand = {(Shift.A, Role.GENERAL_GUARD): 1, (Shift.B, Role.GENERAL_GUARD): 1}
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)

    p_on = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=FF,
                   forbid_adjacent_shifts=True)
    r_on = solve(p_on, CFG)
    assert isinstance(r_on, Solved)
    assert r_on.coverage.total_uncovered == 30  # 1 gap/day, 30 days
    new_assignments = [a for a in r_on.assignments]
    by_day = {}
    for a in new_assignments:
        by_day.setdefault(a.date, set()).add(a.shift)
    assert all(not ({Shift.A, Shift.B} <= shifts) for shifts in by_day.values())

    p_off = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=FF,
                    forbid_adjacent_shifts=False)
    r_off = solve(p_off, CFG)
    assert isinstance(r_off, Solved)
    assert r_off.coverage.total_uncovered == 0


def test_weight_sufficiency_arithmetic():
    """§4.4 proof: with W = S_max + 1, a roster P with fewer uncovered slots
    always beats a roster Q with more uncovered slots, even in the worst case
    (S_P = S_max, the largest possible shortfall; S_Q = 0, the smallest).
    A weight of 1 would get this wrong whenever S_max >= 1:
    obj_w1(Q) = U_Q + 0 = U_P + 1, obj_w1(P) = U_P + S_max >= U_P + 1, so
    weight 1 ties or prefers Q. With W = S_max + 1: obj(P) = W*U_P + S_max,
    obj(Q) = W*(U_P + 1) = W*U_P + W = W*U_P + S_max + 1 > obj(P): P always
    wins, regardless of how bad its shortfall is relative to Q's.
    """
    s_max = 50
    weight = s_max + 1
    u_p, s_p = 10, s_max  # worst-case shortfall for the better-coverage roster
    u_q, s_q = 11, 0      # best-case shortfall for the worse-coverage roster

    obj_weight1_p = 1 * u_p + s_p
    obj_weight1_q = 1 * u_q + s_q
    assert obj_weight1_q <= obj_weight1_p  # a weight of 1 would pick Q (or tie)

    obj_p = weight * u_p + s_p
    obj_q = weight * u_q + s_q
    assert obj_p < obj_q  # the correct weight always picks P


def test_among_coverage_optimal_rosters_minimum_shortfall_returned():
    """Two workers can each cover the one demanded slot per day; only one is
    needed to hit full coverage but preferring the neediest one for the slot
    minimizes total shortfall."""
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    needy = make_worker("needy", Role.GENERAL_GUARD, min_hours=240, max_hours=240)
    filler = make_worker("filler", Role.GENERAL_GUARD, min_hours=0, max_hours=240)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[needy, filler], free_from=FF)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert result.coverage.total_uncovered == 0
    # the solver should favor the needy worker to minimize total shortfall
    needy_hours = 8 * sum(1 for a in result.assignments if a.worker_id == "needy")
    filler_hours = 8 * sum(1 for a in result.assignments if a.worker_id == "filler")
    assert needy_hours >= filler_hours


def test_greedy_trap_cp_sat_covers_everything():
    """Slot Y is reachable by w1 or w2; slot X only by w2. A greedy that
    assigns Y first and arbitrarily picks w2 would strand X. CP-SAT finds the
    full matching (w2->X, w1->Y)."""
    demand = {(Shift.A, Role.GENERAL_GUARD): 1, (Shift.B, Role.GENERAL_GUARD): 1}
    avail_both = frozenset((wd, s) for wd in Weekday for s in Shift)
    avail_b_only = frozenset((wd, Shift.B) for wd in Weekday)
    w1 = make_worker("w1", Role.GENERAL_GUARD, availability=avail_b_only, max_hours=744)
    w2 = make_worker("w2", Role.GENERAL_GUARD, availability=avail_both, max_hours=744)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[w1, w2], free_from=FF)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert result.coverage.total_uncovered == 0


def test_inactive_worker_high_minimum_excluded():
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    inactive = make_worker("inactive", Role.GENERAL_GUARD, min_hours=500, max_hours=500, active=False)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[inactive], free_from=FF)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert not any(a.worker_id == "inactive" for a in result.assignments)
    assert not any(h.worker_id == "inactive" for h in result.hour_shortfalls)
    # the inactive worker contributes no capacity, so the gap is fully unmet (proven)
    assert result.diagnostics.total_lower_bound == 30
    assert "inactive" not in result.diagnostics.worker_shortfall_lower_bounds


def test_tiny_brute_force_check():
    """free_from leaves 2 free shifts (day1 A and B), 2 workers. Enumerate
    every roster; the solver's (uncovered, shortfall) equals the
    lexicographic minimum over all hard-feasible rosters."""
    demand = {(Shift.A, Role.GENERAL_GUARD): 1, (Shift.B, Role.GENERAL_GUARD): 1}
    w1 = make_worker("w1", Role.GENERAL_GUARD, min_hours=8, max_hours=8)
    w2 = make_worker("w2", Role.GENERAL_GUARD, min_hours=0, max_hours=8)
    free_from = (date(YEAR, MONTH, 1), Shift.A)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[w1, w2], free_from=free_from)

    day1 = date(YEAR, MONTH, 1)
    slots = [(day1, Shift.A), (day1, Shift.B)]
    worker_ids = ["w1", "w2", None]  # None = unfilled

    best = None
    for a_worker, b_worker in itertools.product(worker_ids, repeat=2):
        if a_worker is not None and a_worker == b_worker:
            continue  # daily limit / one worker per slot at a time is fine, but demand=1 each; a_worker==b_worker means one worker took both, which is allowed by hard constraints (max_hours 8 = 1 shift though)
        roster = []
        if a_worker:
            roster.append(Assignment(a_worker, day1, Shift.A, Role.GENERAL_GUARD))
        if b_worker:
            roster.append(Assignment(b_worker, day1, Shift.B, Role.GENERAL_GUARD))
        # respect max_hours=8 (1 shift) hard cap manually when enumerating
        hours = {}
        for a in roster:
            hours[a.worker_id] = hours.get(a.worker_id, 0) + 8
        if any(hours.get(w.id, 0) > w.max_hours for w in (w1, w2)):
            continue
        uncovered = 2 - len(roster)
        shortfall = sum(max(0, w.min_hours - hours.get(w.id, 0)) for w in (w1, w2))
        key = (uncovered, shortfall)
        if best is None or key < best:
            best = key

    result = solve(p, CFG)
    assert isinstance(result, Solved)
    new_assignments = [a for a in result.assignments]
    hours = {}
    for a in new_assignments:
        hours[a.worker_id] = hours.get(a.worker_id, 0) + 8
    solver_uncovered = 2 - len(new_assignments)
    solver_shortfall = sum(max(0, w.min_hours - hours.get(w.id, 0)) for w in (w1, w2))
    assert (solver_uncovered, solver_shortfall) == best
