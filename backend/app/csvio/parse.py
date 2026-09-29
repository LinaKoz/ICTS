"""Pure CSV parsing and row validation (P8, P14). No database access.

`parse_csv(data, default_month)` decodes strictly (UTF-8, optional BOM),
matches columns by normalised header name and alias, counts data rows
while iterating (`TOO_MANY_ROWS` at row 5,001) and validates every row.
Row-level problems never raise: they become `RowError`s and the row is
INVALID; other rows are unaffected (partial success).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.contracts.availability import normalize_availability
from app.csvio.errors import DuplicateColumnError, EmptyFileError, InvalidEncodingError, MissingColumnsError
from app.errors import TooManyRowsError
from app.workers.national_id import israeli_id_checksum_ok

MAX_BYTES = 1_048_576  # 1 MB, exact
MAX_ROWS = 5_000
EXPORT_FORMAT = "icts-export-v1"
NAME_MAX = 200
MAX_MONTH_HOURS = 744

# Formula-injection trigger set T (P14): `= + - @ TAB CR '`.
TRIGGERS = ("=", "+", "-", "@", "\t", "\r", "'")

HEADER_ALIASES: dict[str, str] = {
    "id": "national_id",
    "israeli_id": "national_id",
    "id_number": "national_id",
    "name": "full_name",
    "hourly_rate": "hourly_rate_ils",
    "hourly_cost": "hourly_rate_ils",
    "min_hours": "min_monthly_hours",
    "max_hours": "max_monthly_hours",
    "days": "available_days",
    "shifts": "available_shifts",
}
KNOWN_COLUMNS = (
    "national_id",
    "full_name",
    "role",
    "status",
    "effective_month",
    "hourly_rate_ils",
    "min_monthly_hours",
    "max_monthly_hours",
    "availability",
    "available_days",
    "available_shifts",
    "export_format",
)
REQUIRED_COLUMNS = ("national_id", "full_name", "role")

ROLE_ALIASES = {
    "general guard": "GENERAL_GUARD",
    "guard": "GENERAL_GUARD",
    "screener": "SCREENER",
    "supervisor": "SUPERVISOR",
}
STATUS_ALIASES = {"active": "ACTIVE", "inactive": "INACTIVE"}

_DAY_CODES = {
    "mon": "MON", "monday": "MON", "tue": "TUE", "tuesday": "TUE", "wed": "WED", "wednesday": "WED",
    "thu": "THU", "thursday": "THU", "fri": "FRI", "friday": "FRI", "sat": "SAT", "saturday": "SAT",
    "sun": "SUN", "sunday": "SUN",
}
_SHIFT_NAMES = {"a": "A", "b": "B", "c": "C", "morning": "A", "day": "B", "evening": "C"}

_NINE_DIGITS = re.compile(r"[0-9]{9}")
_DIGITS = re.compile(r"[0-9]+")
_SCI = re.compile(r"[0-9]+(\.[0-9]*)?[eE][+-]?[0-9]+")
_DECIMAL = re.compile(r"[0-9]{1,8}(\.[0-9]{1,2})?")
_INT = re.compile(r"[0-9]+(\.0+)?")
_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])")
_SEP = re.compile(r"[|;,]")
_SPACES = re.compile(r"[\s_-]+")

_HINT = "; spreadsheets often drop leading zeros"


@dataclass
class RowError:
    code: str
    message: str
    field: str | None = None


@dataclass
class ParsedContract:
    hourly_rate_ils: Decimal
    min_hours: int
    max_hours: int
    availability: list[str]  # normalised MON..SUN then A..C, same helper as the DB write path


@dataclass
class ParsedRow:
    line: int  # physical line of the record's last line in the file
    national_id: str
    full_name: str
    role: str | None
    status: str | None
    effective_month: date | None
    contract: ParsedContract | None
    errors: list[RowError] = field(default_factory=list)
    export_row: bool = False


@dataclass
class ParsedFile:
    rows: list[ParsedRow]
    unknown_columns: list[str]
    columns: list[str]  # canonical names present, file order


def normalize_header(raw: str) -> str:
    h = _SPACES.sub("_", raw.strip().lower())
    return HEADER_ALIASES.get(h, h)


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")  # strict; a leading BOM is dropped
    except UnicodeDecodeError as exc:
        raise InvalidEncodingError(f"the file is not valid UTF-8 (byte offset {exc.start})") from None


def per_day_form(availability: list[str]) -> str:
    """`["MON:A", "MON:B", "TUE:C"]` -> `"MON:AB|TUE:C"`: the lossless per-day
    form that export writes and the preview shows."""
    by_day: dict[str, str] = {}
    for tok in normalize_availability(list(availability)):
        day, _, shift = tok.partition(":")
        by_day[day] = by_day.get(day, "") + shift
    return "|".join(f"{d}:{s}" for d, s in by_day.items())


def unescape_export_name(name: str) -> str:
    """Inverse of `escape_name` (export rows only): drop exactly one leading
    apostrophe when the second character is a trigger."""
    if len(name) >= 2 and name[0] == "'" and name[1] in TRIGGERS:
        return name[1:]
    return name


def escape_name(name: str) -> str:
    return "'" + name if name and name[0] in TRIGGERS else name


def _enum(raw: str, aliases: dict[str, str]) -> str | None:
    return aliases.get(_SPACES.sub(" ", raw.strip().lower()))


def _id_errors(nid: str) -> list[RowError]:
    if not nid:
        return [RowError("REQUIRED_FIELD", "national_id is required", "national_id")]
    if _NINE_DIGITS.fullmatch(nid):
        if not israeli_id_checksum_ok(nid):
            return [RowError("ID_CHECKSUM", "national ID fails the Israeli ID checksum", "national_id")]
        return []
    if _DIGITS.fullmatch(nid):
        hint = _HINT if len(nid) < 9 else ""
        return [RowError("ID_LENGTH", f"must be exactly 9 digits (got {len(nid)}){hint}", "national_id")]
    if _SCI.fullmatch(nid):
        return [RowError("ID_FORMAT", f"{nid!r} looks like scientific notation; must be exactly 9 digits{_HINT}", "national_id")]
    return [RowError("ID_FORMAT", f"{nid!r} must be exactly 9 digits (0-9 only)", "national_id")]


def _tokens(raw: str) -> list[str]:
    return [t.strip() for t in _SEP.split(raw) if t.strip()]


def _shifts_of(token: str) -> list[str] | None:
    low = token.strip().lower()
    if low in _SHIFT_NAMES:
        return [_SHIFT_NAMES[low]]
    if low and all(c in "abc" for c in low):
        return [c.upper() for c in low]
    return None


def _parse_availability(av: str, days: str, shifts: str, errors: list[RowError]) -> tuple[list[str], bool]:
    """Returns (pairs, anything_filled). Appends availability errors."""
    filled_a, filled_d, filled_s = bool(av.strip()), bool(days.strip()), bool(shifts.strip())
    if not (filled_a or filled_d or filled_s):
        return [], False
    if filled_a and (filled_d or filled_s):
        errors.append(RowError("AMBIGUOUS_AVAILABILITY", "fill either availability or available_days + available_shifts, not both", "availability"))
        return [], True
    if filled_d != filled_s:
        which = "available_shifts" if filled_d else "available_days"
        errors.append(RowError("INCOMPLETE_AVAILABILITY", f"available_days and available_shifts must be given together ({which} is empty)", which))
        return [], True
    pairs: list[str] = []
    bad = False
    if filled_a:
        for tok in _tokens(av):
            day, sep, sh = tok.partition(":")
            letters = _shifts_of(sh) if sep else None
            code = _DAY_CODES.get(day.strip().lower())
            if code is None or letters is None:
                errors.append(RowError("UNKNOWN_AVAILABILITY_TOKEN", f"unknown availability token {tok!r}; expected e.g. MON:AB", "availability"))
                bad = True
                continue
            pairs += [f"{code}:{s}" for s in letters]
    else:
        day_codes, shift_letters = [], []
        for tok in _tokens(days):
            code = _DAY_CODES.get(tok.lower())
            if code is None:
                errors.append(RowError("UNKNOWN_AVAILABILITY_TOKEN", f"unknown day {tok!r}; expected Sun..Sat or a full day name", "available_days"))
                bad = True
            else:
                day_codes.append(code)
        for tok in _tokens(shifts):
            letters = _shifts_of(tok)
            if letters is None:
                errors.append(RowError("UNKNOWN_AVAILABILITY_TOKEN", f"unknown shift {tok!r}; expected A/B/C or Morning/Day/Evening", "available_shifts"))
                bad = True
            else:
                shift_letters += letters
        pairs = [f"{d}:{s}" for d in day_codes for s in shift_letters]
    if bad:
        return [], True
    if not pairs:
        errors.append(RowError("MISSING_AVAILABILITY", "availability has no day/shift pairs", "availability"))
        return [], True
    return normalize_availability(pairs), True


def _int(raw: str, name: str, errors: list[RowError]) -> int | None:
    v = raw.strip()
    if not _INT.fullmatch(v):
        errors.append(RowError("INVALID_HOURS", f"{name} must be a whole number of hours (got {v!r})", name))
        return None
    n = int(v.split(".")[0])
    if n > MAX_MONTH_HOURS:
        errors.append(RowError("INVALID_HOURS", f"{name} must be at most {MAX_MONTH_HOURS}", name))
        return None
    return n


def _validate_row(cells: dict[str, str], line: int, default_month: date) -> ParsedRow:
    errors: list[RowError] = []
    fmt = cells.get("export_format", "").strip()
    export_row = fmt == EXPORT_FORMAT
    if fmt and not export_row:
        errors.append(RowError("UNKNOWN_EXPORT_FORMAT", f"unknown export_format {fmt!r}; expected {EXPORT_FORMAT!r} or empty", "export_format"))

    nid = cells.get("national_id", "").strip()
    errors += _id_errors(nid)

    raw_name = cells.get("full_name", "")
    if export_row:
        name = unescape_export_name(raw_name)
    else:
        name = raw_name.strip()  # external names are verbatim apart from trimming, like the UI
    if not name.strip():
        errors.append(RowError("REQUIRED_FIELD", "full_name is required", "full_name"))
    elif len(name) > NAME_MAX:
        errors.append(RowError("NAME_TOO_LONG", f"full_name must be at most {NAME_MAX} characters", "full_name"))

    role = _enum(cells.get("role", ""), ROLE_ALIASES)
    if not cells.get("role", "").strip():
        errors.append(RowError("REQUIRED_FIELD", "role is required", "role"))
    elif role is None:
        errors.append(RowError("UNKNOWN_ROLE", f"unknown role {cells['role'].strip()!r}; expected General Guard, Screener or Supervisor", "role"))

    raw_status = cells.get("status", "").strip()
    status = "ACTIVE"
    if raw_status:
        s = _enum(raw_status, STATUS_ALIASES)
        if s is None:
            errors.append(RowError("UNKNOWN_STATUS", f"unknown status {raw_status!r}; expected Active or Inactive", "status"))
        else:
            status = s

    raw_month = cells.get("effective_month", "").strip()
    month = default_month
    if raw_month:
        m = _MONTH.fullmatch(raw_month)
        if m:
            month = date(int(m.group(1)), int(m.group(2)), 1)
        else:
            errors.append(RowError("INVALID_MONTH", f"effective_month must be YYYY-MM (got {raw_month!r})", "effective_month"))

    rate_raw = cells.get("hourly_rate_ils", "").strip()
    min_raw = cells.get("min_monthly_hours", "").strip()
    max_raw = cells.get("max_monthly_hours", "").strip()
    av_errors: list[RowError] = []
    pairs, av_filled = _parse_availability(
        cells.get("availability", ""), cells.get("available_days", ""), cells.get("available_shifts", ""), av_errors
    )
    scalars = {"hourly_rate_ils": rate_raw, "min_monthly_hours": min_raw, "max_monthly_hours": max_raw}
    filled = [k for k, v in scalars.items() if v]
    contract: ParsedContract | None = None
    if filled or av_filled:
        missing = [k for k, v in scalars.items() if not v]
        if missing:
            errors.append(RowError("INCOMPLETE_CONTRACT", "contract columns must all be filled or all empty; empty: " + ", ".join(missing), missing[0]))
            errors += av_errors
        else:
            errors += av_errors
            if not av_filled:
                errors.append(RowError("MISSING_AVAILABILITY", "availability is required when contract columns are filled", "availability"))
            rate: Decimal | None = None
            if not _DECIMAL.fullmatch(rate_raw) or Decimal(rate_raw) <= 0:
                errors.append(RowError("INVALID_RATE", f"hourly_rate_ils must be a positive amount with at most 2 decimals (got {rate_raw!r})", "hourly_rate_ils"))
            else:
                rate = Decimal(rate_raw).quantize(Decimal("0.01"))
            lo = _int(min_raw, "min_monthly_hours", errors)
            hi = _int(max_raw, "max_monthly_hours", errors)
            if lo is not None and hi is not None and lo > hi:
                errors.append(RowError("HOURS_RANGE", "min_monthly_hours must not exceed max_monthly_hours", "min_monthly_hours"))
            elif rate is not None and lo is not None and hi is not None and pairs:
                contract = ParsedContract(rate, lo, hi, pairs)

    return ParsedRow(
        line=line,
        national_id=nid,
        full_name=name,
        role=role,
        status=status,
        effective_month=month if (contract is not None or filled or av_filled) else None,
        contract=contract,
        errors=errors,
        export_row=export_row,
    )


def parse_csv(data: bytes, default_month: date, max_rows: int = MAX_ROWS) -> ParsedFile:
    text = decode(data)
    reader = csv.reader(io.StringIO(text, newline=""))
    header: list[str] | None = None
    for record in reader:
        if any(c.strip() for c in record):
            header = record
            break
    if header is None:
        raise EmptyFileError("the file is empty: a header row is required")

    canon = [normalize_header(h) for h in header]
    seen: dict[str, int] = {}
    for c in canon:
        seen[c] = seen.get(c, 0) + 1
    dupes = sorted(c for c, n in seen.items() if n > 1 and c)
    if dupes:
        raise DuplicateColumnError("duplicate columns after normalisation: " + ", ".join(dupes), details={"columns": dupes})
    missing = [c for c in REQUIRED_COLUMNS if c not in seen]
    if missing:
        raise MissingColumnsError("missing required columns: " + ", ".join(missing), details={"missing": missing})
    unknown = [h.strip() for h, c in zip(header, canon) if c not in KNOWN_COLUMNS and h.strip()]

    rows: list[ParsedRow] = []
    for record in reader:
        if not any(c.strip() for c in record):
            continue  # blank lines do not count
        if len(rows) >= max_rows:
            raise TooManyRowsError(f"the file has more than {max_rows} data rows")
        cells = {c: (record[i] if i < len(record) else "") for i, c in enumerate(canon) if c in KNOWN_COLUMNS}
        row = _validate_row(cells, reader.line_num, default_month)
        if len(record) > len(header) and any(c.strip() for c in record[len(header):]):
            row.errors.append(RowError("TOO_MANY_FIELDS", f"the row has {len(record)} fields but the header has {len(header)}"))
        rows.append(row)

    counts: dict[str, int] = {}
    for r in rows:
        if r.national_id:
            counts[r.national_id] = counts.get(r.national_id, 0) + 1
    for r in rows:
        if r.national_id and counts[r.national_id] > 1:
            r.errors.append(RowError("DUPLICATE_IN_FILE", f"national ID {r.national_id} appears {counts[r.national_id]} times in this file", "national_id"))
    return ParsedFile(rows=rows, unknown_columns=unknown, columns=[c for c in canon if c in KNOWN_COLUMNS])
