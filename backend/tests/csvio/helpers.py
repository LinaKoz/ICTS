"""Test helpers for the T6 CSV tests."""
from __future__ import annotations

import csv
import io

BOM = "﻿"


def valid_id(body8: int | str) -> str:
    """A checksum-valid 9-digit Israeli ID whose first 8 digits are `body8` (zero-padded)."""
    body = str(body8).zfill(8)
    total = 0
    for i, ch in enumerate(body):
        n = int(ch) * (1 + i % 2)
        total += n - 9 if n > 9 else n
    return body + str((10 - total % 10) % 10)


def csv_text(header: list[str], rows: list[list[str]], bom: bool = False) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return ((BOM if bom else "") + buf.getvalue()).encode("utf-8")


FULL = ["national_id", "full_name", "role", "status", "effective_month", "hourly_rate_ils",
        "min_monthly_hours", "max_monthly_hours", "availability"]
ALL_DAYS = "MON:ABC|TUE:ABC|WED:ABC|THU:ABC|FRI:ABC|SAT:ABC|SUN:ABC"


def row(nid, name="Alice", role="Guard", status="", month="2026-10", rate="40", lo="0", hi="200", av=ALL_DAYS):
    return [nid, name, role, status, month, rate, lo, hi, av]
