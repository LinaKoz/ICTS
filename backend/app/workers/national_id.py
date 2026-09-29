"""Israeli national ID validation (§3: the DB checks `^[0-9]{9}$`, the
checksum is enforced here). Pure; shared by the workers API and, later,
CSV import (P14: string IDs, never padded)."""
from __future__ import annotations

import re

_NINE_DIGITS = re.compile(r"[0-9]{9}")


def israeli_id_checksum_ok(national_id: str) -> bool:
    """Luhn-style Israeli ID check: digits are weighted 1,2,1,2,..., a
    two-digit product contributes its digit sum, and the total must be
    divisible by 10. Expects exactly 9 ASCII digits."""
    total = 0
    for i, ch in enumerate(national_id):
        n = int(ch) * (1 + i % 2)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def national_id_error(national_id: str) -> str | None:
    """A human-readable reason the ID is invalid, or `None` if it is valid.
    The value is used as given (callers trim); short IDs are never padded."""
    if not _NINE_DIGITS.fullmatch(national_id):
        hint = ""
        if national_id.isascii() and national_id.isdigit() and len(national_id) < 9:
            hint = f" (got {len(national_id)}); spreadsheets often drop leading zeros"
        return f"national ID must be exactly 9 digits{hint}"
    if not israeli_id_checksum_ok(national_id):
        return "national ID fails the Israeli ID checksum"
    return None
