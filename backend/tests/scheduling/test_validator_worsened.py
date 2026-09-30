"""§4.9 Validator and worsened."""
from datetime import date

from app.scheduling import (
    Assignment, DEFAULT_DEMAND, Problem, Role, Shift, ViolationCode, validate_roster, worsened,
)
from tests.scheduling.conftest import make_worker

D = date(2026, 11, 10)  # a Tuesday
D_NEXT = date(2026, 11, 11)


def problem(workers, forbid_adjacent_shifts=False, neighbor_assignments=()):
    return Problem(year=2026, month=11, demand=DEFAULT_DEMAND, workers=workers,
                   free_from=(date(2026, 11, 1), Shift.A),
                   forbid_adjacent_shifts=forbid_adjacent_shifts,
                   neighbor_assignments=neighbor_assignments)


def test_valid_roster_no_violations():
    w = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=160)
    p = problem([w])
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD)]
    assert validate_roster(p, roster) == []


def test_inactive_worker():
    w = make_worker("w1", Role.GENERAL_GUARD, active=False)
    p = problem([w])
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD)]
    v = validate_roster(p, roster)
    assert len(v) == 1 and v[0].code == ViolationCode.INACTIVE_WORKER
    assert v[0].key == ("w1", D, Shift.A) and v[0].magnitude == 1


def test_unknown_worker():
    p = problem([make_worker("w1", Role.GENERAL_GUARD)])
    roster = [Assignment("ghost", D, Shift.A, Role.GENERAL_GUARD)]
    v = validate_roster(p, roster)
    assert len(v) == 1 and v[0].code == ViolationCode.UNKNOWN_WORKER
    assert v[0].magnitude == 1


def test_wrong_role():
    w = make_worker("w1", Role.SCREENER)
    p = problem([w])
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.WRONG_ROLE]
    assert len(v) == 1 and v[0].magnitude == 1


def test_unavailable():
    w = make_worker("w1", Role.GENERAL_GUARD, availability=frozenset())
    p = problem([w])
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.UNAVAILABLE]
    assert len(v) == 1 and v[0].magnitude == 1


def test_out_of_month():
    w = make_worker("w1", Role.GENERAL_GUARD)
    p = problem([w])
    roster = [Assignment("w1", date(2026, 12, 1), Shift.A, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.OUT_OF_MONTH]
    assert len(v) == 1 and v[0].magnitude == 1


def test_duplicate_assignment():
    w = make_worker("w1", Role.GENERAL_GUARD)
    p = problem([w])
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD)] * 3
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.DUPLICATE_ASSIGNMENT]
    assert len(v) == 1 and v[0].magnitude == 2  # copies - 1


def test_daily_limit():
    w = make_worker("w1", Role.GENERAL_GUARD)
    p = problem([w])
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD),
              Assignment("w1", D, Shift.B, Role.GENERAL_GUARD),
              Assignment("w1", D, Shift.C, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.DAILY_LIMIT]
    assert len(v) == 1 and v[0].magnitude == 1 and v[0].key == ("w1", D)  # 3 shifts - 2


def test_max_hours():
    w = make_worker("w1", Role.GENERAL_GUARD, max_hours=8)
    p = problem([w])
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD),
              Assignment("w1", D, Shift.B, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.MAX_HOURS]
    assert len(v) == 1 and v[0].magnitude == 8 and v[0].key == ("w1",)  # 16 - 8


def test_overstaffed():
    w1 = make_worker("w1", Role.GENERAL_GUARD)
    w2 = make_worker("w2", Role.GENERAL_GUARD)
    w3 = make_worker("w3", Role.GENERAL_GUARD)
    p = problem([w1, w2, w3])  # demand for A/GENERAL_GUARD is 2
    roster = [Assignment(w, D, Shift.A, Role.GENERAL_GUARD) for w in ("w1", "w2", "w3")]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.OVERSTAFFED]
    assert len(v) == 1 and v[0].magnitude == 1 and v[0].key == (D, Shift.A, Role.GENERAL_GUARD)


# --- ADJACENT_SHIFTS ---

def test_adjacent_a_b_rule_on():
    w = make_worker("w1", Role.GENERAL_GUARD)
    p = problem([w], forbid_adjacent_shifts=True)
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD), Assignment("w1", D, Shift.B, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.ADJACENT_SHIFTS]
    assert len(v) == 1 and v[0].key == ("w1", D, Shift.A) and v[0].magnitude == 1


def test_adjacent_b_c_rule_on():
    w = make_worker("w1", Role.GENERAL_GUARD)
    p = problem([w], forbid_adjacent_shifts=True)
    roster = [Assignment("w1", D, Shift.B, Role.GENERAL_GUARD), Assignment("w1", D, Shift.C, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.ADJACENT_SHIFTS]
    assert len(v) == 1 and v[0].key == ("w1", D, Shift.B)


def test_adjacent_c_next_day_a_rule_on():
    w = make_worker("w1", Role.GENERAL_GUARD)
    p = problem([w], forbid_adjacent_shifts=True)
    roster = [Assignment("w1", D, Shift.C, Role.GENERAL_GUARD), Assignment("w1", D_NEXT, Shift.A, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.ADJACENT_SHIFTS]
    assert len(v) == 1 and v[0].key == ("w1", D, Shift.C)


def test_adjacent_neighbor_prev_month_c_to_1st_a():
    w = make_worker("w1", Role.GENERAL_GUARD)
    prev_last = date(2026, 10, 31)
    neighbor = (Assignment("w1", prev_last, Shift.C, Role.GENERAL_GUARD),)
    p = problem([w], forbid_adjacent_shifts=False, neighbor_assignments=neighbor)
    roster = [Assignment("w1", date(2026, 11, 1), Shift.A, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.ADJACENT_SHIFTS]
    assert len(v) == 1 and v[0].key == ("w1", prev_last, Shift.C)


def test_adjacent_rule_off_a_b_b_c_c_next_a_not_reported():
    w1 = make_worker("w1", Role.GENERAL_GUARD)
    p = problem([w1], forbid_adjacent_shifts=False)
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD), Assignment("w1", D, Shift.B, Role.GENERAL_GUARD)]
    assert not any(v.code == ViolationCode.ADJACENT_SHIFTS for v in validate_roster(p, roster))

    roster = [Assignment("w1", D, Shift.B, Role.GENERAL_GUARD), Assignment("w1", D, Shift.C, Role.GENERAL_GUARD)]
    assert not any(v.code == ViolationCode.ADJACENT_SHIFTS for v in validate_roster(p, roster))

    roster = [Assignment("w1", D, Shift.C, Role.GENERAL_GUARD), Assignment("w1", D_NEXT, Shift.A, Role.GENERAL_GUARD)]
    assert not any(v.code == ViolationCode.ADJACENT_SHIFTS for v in validate_roster(p, roster))


def test_adjacent_rule_off_neighbor_pair_still_reported():
    w = make_worker("w1", Role.GENERAL_GUARD)
    prev_last = date(2026, 10, 31)
    neighbor = (Assignment("w1", prev_last, Shift.C, Role.GENERAL_GUARD),)
    p = problem([w], forbid_adjacent_shifts=False, neighbor_assignments=neighbor)
    roster = [Assignment("w1", date(2026, 11, 1), Shift.A, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.ADJACENT_SHIFTS]
    assert len(v) == 1


def test_rule_off_three_shifts_still_daily_limit():
    w = make_worker("w1", Role.GENERAL_GUARD)
    p = problem([w], forbid_adjacent_shifts=False)
    roster = [Assignment("w1", D, Shift.A, Role.GENERAL_GUARD),
              Assignment("w1", D, Shift.B, Role.GENERAL_GUARD),
              Assignment("w1", D, Shift.C, Role.GENERAL_GUARD)]
    v = [x for x in validate_roster(p, roster) if x.code == ViolationCode.DAILY_LIMIT]
    assert len(v) == 1 and v[0].magnitude == 1


# --- worsened ---

def test_worsened_new_key_reported():
    from app.scheduling import Violation
    before = []
    after = [Violation(ViolationCode.MAX_HOURS, ("w1",), 5, ())]
    assert worsened(before, after) == after


def test_worsened_same_key_higher_magnitude_reported():
    from app.scheduling import Violation
    before = [Violation(ViolationCode.MAX_HOURS, ("w1",), 16, ())]
    after = [Violation(ViolationCode.MAX_HOURS, ("w1",), 24, ())]
    assert worsened(before, after) == after


def test_worsened_same_or_lower_magnitude_not_reported():
    from app.scheduling import Violation
    before = [Violation(ViolationCode.MAX_HOURS, ("w1",), 16, ())]
    same = [Violation(ViolationCode.MAX_HOURS, ("w1",), 16, ())]
    lower = [Violation(ViolationCode.MAX_HOURS, ("w1",), 10, ())]
    assert worsened(before, same) == []
    assert worsened(before, lower) == []


# --- metrics ---

def test_metrics_recomputed_gaps_and_shortfalls():
    from app.scheduling import roster_metrics
    w = make_worker("w1", Role.SUPERVISOR, min_hours=16, max_hours=160)
    p = problem([w])
    roster = [Assignment("w1", D, Shift.A, Role.SUPERVISOR)]
    m = roster_metrics(p, roster)
    gap = next(g for g in m.coverage_gaps if g.date == D and g.shift == Shift.A and g.role == Role.SUPERVISOR)
    assert gap.required == 1 and gap.assigned == 1 and gap.missing == 0
    shortfall = next(h for h in m.hour_shortfalls if h.worker_id == "w1")
    assert shortfall.min_hours == 16 and shortfall.assigned_hours == 8 and shortfall.missing_hours == 8


def test_metrics_inactive_workers_absent_from_shortfalls():
    from app.scheduling import roster_metrics
    w = make_worker("w1", Role.SUPERVISOR, min_hours=100, max_hours=160, active=False)
    p = problem([w])
    m = roster_metrics(p, [])
    assert not any(h.worker_id == "w1" for h in m.hour_shortfalls)
