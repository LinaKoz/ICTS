"""Availability normalisation for contract versions (§3: `availability`
is a sorted `["MON:A", ...]`). Sorted here means weekday order (MON..SUN)
then shift (A..C), which is also the order the seed uses. Shared with CSV
import, which must store the same representation."""
from __future__ import annotations

_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_SHIFTS = ("A", "B", "C")


def normalize_availability(tokens: list[str]) -> list[str]:
    """Upper-cases, de-duplicates and sorts `DAY:SHIFT` tokens. Raises
    `ValueError` naming the first unknown token."""
    seen: set[tuple[int, int]] = set()
    for raw in tokens:
        token = raw.strip().upper()
        day, sep, shift = token.partition(":")
        if not sep or day not in _DAYS or shift not in _SHIFTS:
            raise ValueError(f"unknown availability token {raw!r}; expected e.g. MON:A")
        seen.add((_DAYS.index(day), _SHIFTS.index(shift)))
    return [f"{_DAYS[d]}:{_SHIFTS[s]}" for d, s in sorted(seen)]
