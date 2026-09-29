"""Pure parsing tests (§8 T6 Review-CSV support): headers, aliases, optional
columns, roles/statuses, availability forms, IDs, formula protection, limits."""
from __future__ import annotations

from datetime import date

import pytest

from app.csvio.errors import DuplicateColumnError, EmptyFileError, InvalidEncodingError, MissingColumnsError
from app.csvio.parse import MAX_BYTES, MAX_ROWS, escape_name, parse_csv, unescape_export_name
from app.errors import TooManyRowsError
from tests.csvio.helpers import ALL_DAYS, FULL, csv_text, row, valid_id

DEFAULT = date(2026, 9, 1)
ID = valid_id(1234567)


def one(header, cells, **kw):
    parsed = parse_csv(csv_text(header, [cells], **kw), DEFAULT)
    assert len(parsed.rows) == 1
    return parsed.rows[0]


def codes(r):
    return [e.code for e in r.errors]


# --- headers -----------------------------------------------------------------


def test_shuffled_columns_and_aliases_match():
    header = ["Hourly Cost", "Israeli ID", "Name", "Role", "Max Hours", "min-hours", "Availability"]
    r = one(header, ["45.5", ID, "Dana", "Screener", "180", "10", "MON:A"])
    assert not r.errors
    assert (r.national_id, r.full_name, r.role) == (ID, "Dana", "SCREENER")
    assert (str(r.contract.hourly_rate_ils), r.contract.min_hours, r.contract.max_hours) == ("45.50", 10, 180)
    assert r.contract.availability == ["MON:A"]


def test_missing_required_columns_lists_them():
    with pytest.raises(MissingColumnsError) as e:
        parse_csv(csv_text(["national_id", "status"], []), DEFAULT)
    assert e.value.status_code == 400 and e.value.code == "MISSING_COLUMNS"
    assert e.value.details == {"missing": ["full_name", "role"]}


def test_duplicate_normalised_headers_rejected():
    with pytest.raises(DuplicateColumnError) as e:
        parse_csv(csv_text(["national_id", "Full Name", "full-name", "role"], []), DEFAULT)
    assert e.value.code == "DUPLICATE_COLUMN"
    with pytest.raises(DuplicateColumnError):  # an alias colliding with its canonical name
        parse_csv(csv_text(["national_id", "id", "full_name", "role"], []), DEFAULT)


def test_unknown_columns_are_listed_and_ignored():
    parsed = parse_csv(csv_text(["national_id", "full_name", "role", "Badge Colour"], [[ID, "A", "guard", "red"]]), DEFAULT)
    assert parsed.unknown_columns == ["Badge Colour"] and not parsed.rows[0].errors


def test_bom_accepted_and_empty_file():
    assert not one(["national_id", "full_name", "role"], [ID, "A", "guard"], bom=True).errors
    with pytest.raises(EmptyFileError):
        parse_csv(b"\r\n\r\n", DEFAULT)


def test_blank_lines_are_skipped():
    data = b"national_id,full_name,role\r\n\r\n" + f"{ID},A,guard\r\n\r\n".encode()
    assert len(parse_csv(data, DEFAULT).rows) == 1


# --- optional columns, worker-only rows ---------------------------------------


def test_defaults_status_active_and_month_resolved():
    r = one(["national_id", "full_name", "role", "hourly_rate_ils", "min_monthly_hours", "max_monthly_hours", "availability"],
            [ID, "A", "guard", "40", "0", "100", "MON:A"])
    assert r.status == "ACTIVE" and r.effective_month == DEFAULT
    r = one(FULL, row(ID, status="", month=""))
    assert r.status == "ACTIVE" and r.effective_month == DEFAULT


def test_explicit_month_and_bad_month():
    assert one(FULL, row(ID, month="2026-11")).effective_month == date(2026, 11, 1)
    assert "INVALID_MONTH" in codes(one(FULL, row(ID, month="2026-13")))
    assert "INVALID_MONTH" in codes(one(FULL, row(ID, month="Nov 2026")))


def test_worker_only_row_has_no_contract():
    r = one(FULL, [ID, "A", "guard", "", "", "", "", "", ""])
    assert not r.errors and r.contract is None and r.effective_month is None
    r = one(["national_id", "full_name", "role"], [ID, "A", "guard"])  # contract columns absent altogether
    assert not r.errors and r.contract is None


@pytest.mark.parametrize("cells", [
    [ID, "A", "guard", "", "", "40", "", "", ""],  # rate only
    [ID, "A", "guard", "", "", "", "0", "100", "MON:A"],  # rate missing
    [ID, "A", "guard", "", "", "", "", "", "MON:A"],  # availability only
    [ID, "A", "guard", "", "", "40", "", "100", "MON:A"],  # min missing
])
def test_partial_contract_is_incomplete(cells):
    assert "INCOMPLETE_CONTRACT" in codes(one(FULL, cells))


def test_contract_value_validation():
    assert "INVALID_RATE" in codes(one(FULL, row(ID, rate="0")))
    assert "INVALID_RATE" in codes(one(FULL, row(ID, rate="-5")))
    assert "INVALID_RATE" in codes(one(FULL, row(ID, rate="4.555")))
    assert "INVALID_HOURS" in codes(one(FULL, row(ID, hi="745")))
    assert "INVALID_HOURS" in codes(one(FULL, row(ID, lo="x")))
    assert "HOURS_RANGE" in codes(one(FULL, row(ID, lo="100", hi="50")))
    assert not one(FULL, row(ID, lo="0", hi="744")).errors


# --- role / status aliases -----------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("General Guard", "GENERAL_GUARD"), ("general-guard", "GENERAL_GUARD"), ("GENERAL_GUARD", "GENERAL_GUARD"),
    ("Guard", "GENERAL_GUARD"), ("  gUaRd ", "GENERAL_GUARD"), ("Screener", "SCREENER"), ("SCREENER", "SCREENER"),
    ("Supervisor", "SUPERVISOR"), ("supervisor", "SUPERVISOR"),
])
def test_role_aliases(raw, expected):
    assert one(FULL, row(ID, role=raw)).role == expected


def test_unknown_role_and_status_are_invalid():
    assert "UNKNOWN_ROLE" in codes(one(FULL, row(ID, role="Janitor")))
    assert "UNKNOWN_STATUS" in codes(one(FULL, row(ID, status="Retired")))
    assert "REQUIRED_FIELD" in codes(one(FULL, row(ID, role="")))


@pytest.mark.parametrize("raw,expected", [("Active", "ACTIVE"), ("INACTIVE", "INACTIVE"), ("inactive", "INACTIVE"), ("", "ACTIVE")])
def test_status_aliases(raw, expected):
    assert one(FULL, row(ID, status=raw)).status == expected


# --- availability ----------------------------------------------------------------


def brief(days, shifts):
    return one(["national_id", "full_name", "role", "hourly_rate_ils", "min_monthly_hours", "max_monthly_hours", "available_days", "available_shifts"],
               [ID, "A", "guard", "40", "0", "100", days, shifts])


def test_brief_form_cross_product():
    r = brief("Sun|Mon", "A|C")
    assert r.contract.availability == ["MON:A", "MON:C", "SUN:A", "SUN:C"]  # stored order MON..SUN, A..C


def test_brief_form_names_letters_and_separators():
    assert brief("Sunday;Monday", "Morning|Evening").contract.availability == brief("Sun|Mon", "AC").contract.availability
    assert brief("wednesday", "Day").contract.availability == ["WED:B"]
    assert brief("Mon,Tue", "A,B").contract.availability == ["MON:A", "MON:B", "TUE:A", "TUE:B"]  # the quoted comma form
    assert brief("Mon|Mon|MON", "A|A|A").contract.availability == ["MON:A"]  # duplicates ignored


def test_per_day_form_and_equivalence_with_brief():
    r = one(FULL, row(ID, av="MON:AB|TUE:ABC|FRI:C"))
    assert r.contract.availability == ["MON:A", "MON:B", "TUE:A", "TUE:B", "TUE:C", "FRI:C"]
    assert brief("Mon|Tue", "A|B").contract.availability == one(FULL, row(ID, av="MON:AB|TUE:AB")).contract.availability


def test_availability_error_codes():
    h = ["national_id", "full_name", "role", "hourly_rate_ils", "min_monthly_hours", "max_monthly_hours",
         "availability", "available_days", "available_shifts"]
    base = [ID, "A", "guard", "40", "0", "100"]
    assert "AMBIGUOUS_AVAILABILITY" in codes(one(h, base + ["MON:A", "Mon", "A"]))
    assert "AMBIGUOUS_AVAILABILITY" in codes(one(h, base + ["MON:A", "Mon", ""]))
    assert "INCOMPLETE_AVAILABILITY" in codes(one(h, base + ["", "Mon", ""]))
    assert "INCOMPLETE_AVAILABILITY" in codes(one(h, base + ["", "", "A"]))
    assert "MISSING_AVAILABILITY" in codes(one(h, base + ["", "", ""]))
    assert "MISSING_AVAILABILITY" in codes(one(h, base + ["|", "", ""]))
    bad = one(h, base + ["MON:A|FUNDAY:B", "", ""])
    assert codes(bad) == ["UNKNOWN_AVAILABILITY_TOKEN"] and "FUNDAY:B" in bad.errors[0].message
    bad = one(h, base + ["", "Mon|Blursday", "A"])
    assert "Blursday" in bad.errors[0].message
    bad = one(h, base + ["", "Mon", "A|X"])
    assert "'X'" in bad.errors[0].message


# --- IDs ---------------------------------------------------------------------------


def test_leading_zero_id_kept_as_string():
    r = one(FULL, row("012345674"))
    assert not r.errors and r.national_id == "012345674"


def test_id_length_hint_and_no_padding():
    r = one(FULL, row("12345674"))
    assert codes(r) == ["ID_LENGTH"]
    assert "exactly 9 digits (got 8)" in r.errors[0].message and "leading zeros" in r.errors[0].message
    assert r.national_id == "12345674"  # nothing padded
    assert codes(one(FULL, row("1234567890"))) == ["ID_LENGTH"]


def test_id_format_and_checksum():
    r = one(FULL, row("1.23E+08"))
    assert codes(r) == ["ID_FORMAT"] and "leading zeros" in r.errors[0].message
    assert codes(one(FULL, row("12345678a"))) == ["ID_FORMAT"]
    assert codes(one(FULL, row("١٢٣٤٥٦٧٨٩"))) == ["ID_FORMAT"]  # non-ASCII digits
    assert codes(one(FULL, row("111111111"))) == ["ID_CHECKSUM"]
    assert codes(one(FULL, row(""))) == ["REQUIRED_FIELD"]
    assert not one(FULL, row(f"  {ID}  ")).errors  # trimmed


# --- duplicates in file (P8) ----------------------------------------------------------


def test_duplicate_ids_are_all_invalid_others_processed():
    other = valid_id(7654321)
    parsed = parse_csv(csv_text(FULL, [row(ID, "One"), row(other, "Two"), row(ID, "Three")]), DEFAULT)
    assert [codes(r) for r in parsed.rows] == [["DUPLICATE_IN_FILE"], [], ["DUPLICATE_IN_FILE"]]


# --- formula protection --------------------------------------------------------------


@pytest.mark.parametrize("name", ["=x", "+x", "-x", "@x", "'Neil", "'=x", "Neil"])
def test_external_rows_are_verbatim(name):
    assert one(["national_id", "full_name", "role"], [ID, name, "guard"]).full_name == name
    assert one(["national_id", "full_name", "role", "export_format"], [ID, name, "guard", ""]).full_name == name


@pytest.mark.parametrize("stored,expected", [("''Neil", "'Neil"), ("'=x", "=x"), ("'Neil", "'Neil"), ("Neil", "Neil"), ("'", "'"), ("'\tx", "\tx")])
def test_export_rows_are_unescaped(stored, expected):
    r = one(["national_id", "full_name", "role", "export_format"], [ID, stored, "guard", "icts-export-v1"])
    assert r.full_name == expected and r.export_row


def test_unknown_export_format_invalid_and_mixed_file():
    assert codes(one(["national_id", "full_name", "role", "export_format"], [ID, "A", "guard", "other"])) == ["UNKNOWN_EXPORT_FORMAT"]
    other = valid_id(7654321)
    parsed = parse_csv(csv_text(["national_id", "full_name", "role", "export_format"],
                                [[ID, "'=x", "guard", "icts-export-v1"], [other, "'=x", "guard", ""]]), DEFAULT)
    assert [r.full_name for r in parsed.rows] == ["=x", "'=x"]  # appended external row stays verbatim


@pytest.mark.parametrize("name", ["=x", "+x", "-x", "@x", "\tx", "\rx", "'Neil", "'=x", "''", "'", "Neil", "a'b", " lead", "x=1"])
def test_escape_unescape_roundtrip_for_every_name(name):
    assert unescape_export_name(escape_name(name)) == name
    if name and name[0] in "=+-@\t\r'":
        assert escape_name(name) == "'" + name
    else:
        assert escape_name(name) == name


# --- limits ---------------------------------------------------------------------------


def test_row_limit_boundaries():
    def make(n):
        return b"national_id,full_name,role\n" + b"".join(f"{valid_id(i)},N{i},guard\n".encode() for i in range(n))

    assert len(parse_csv(make(MAX_ROWS), DEFAULT).rows) == 5000
    with pytest.raises(TooManyRowsError) as e:
        parse_csv(make(MAX_ROWS + 1), DEFAULT)
    assert e.value.status_code == 413 and e.value.code == "TOO_MANY_ROWS"


def test_blank_lines_and_header_do_not_count_toward_row_limit():
    body = b"national_id,full_name,role\n\n" + b"".join(f"{valid_id(i)},N,guard\n\n".encode() for i in range(MAX_ROWS))
    assert len(parse_csv(body, DEFAULT).rows) == MAX_ROWS


def test_invalid_utf8_is_400():
    with pytest.raises(InvalidEncodingError) as e:
        parse_csv(b"national_id,full_name,role\n" + ID.encode() + b",\xff\xfe,guard\n", DEFAULT)
    assert e.value.status_code == 400 and e.value.code == "INVALID_ENCODING"


def test_hebrew_names_roundtrip_utf8():
    assert one(["national_id", "full_name", "role"], [ID, "דנה כהן", "guard"], bom=True).full_name == "דנה כהן"


def test_max_bytes_constant():
    assert MAX_BYTES == 1_048_576
