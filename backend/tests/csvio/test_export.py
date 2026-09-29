"""§8 T6 export and round trip (P13, P14): an unmodified export re-imports as all
UNCHANGED, names survive both sources, worker-only/no-contract workers are exported."""
from __future__ import annotations

import csv
import io
from datetime import date

import pytest

from app.csvio.parse import TRIGGERS
from tests.conftest import requires_db
from tests.csvio.conftest import count, post_csv
from tests.csvio.helpers import FULL, csv_text, row, valid_id
from tests.rosters.helpers import insert_contract, insert_worker
from tests.workers.scenario import NOW

TRICKY = ["=SUM(A1)", "+1", "-2", "@cmd", "'Neil", "'=x", "''", "Plain Name", "דנה כהן", "a,b \"q\"", "x=1"]


@pytest.fixture()
def world(planner, db, freeze):
    freeze(NOW)
    client, uid = planner
    return client, uid, db


def export(client, month=None):
    r = client.get("/api/exports/workers.csv" + (f"?month={month}" if month else ""))
    assert r.status_code == 200, r.text
    return r


def parse(resp):
    text = resp.content.decode("utf-8")
    assert text.startswith("﻿")  # BOM written for Hebrew in Excel
    return list(csv.DictReader(io.StringIO(text[1:], newline="")))


@requires_db
def test_export_columns_marker_and_headers(world):
    client, uid, db = world
    w = insert_worker(db, valid_id(1), "Alice", "GENERAL_GUARD")
    insert_contract(db, w, uid, effective_month=date(2026, 1, 1), rate="45.50", min_hours=8, max_hours=120,
                    availability=["MON:A", "MON:B", "TUE:C", "SUN:A"])
    insert_worker(db, valid_id(2), "No Contract", "SCREENER", "INACTIVE")
    resp = export(client)
    assert resp.headers["content-type"].startswith("text/csv")
    assert "workers-2026-09.csv" in resp.headers["content-disposition"]
    assert (resp.headers["x-worker-count"], resp.headers["x-no-contract-count"]) == ("2", "1")
    rows = parse(resp)
    assert list(rows[0]) == ["national_id", "full_name", "role", "status", "effective_month", "hourly_rate_ils",
                             "min_monthly_hours", "max_monthly_hours", "availability", "export_format"]
    assert rows[0] == {"national_id": valid_id(1), "full_name": "Alice", "role": "GENERAL_GUARD", "status": "ACTIVE",
                       "effective_month": "2026-01", "hourly_rate_ils": "45.50", "min_monthly_hours": "8",
                       "max_monthly_hours": "120", "availability": "MON:AB|TUE:C|SUN:A", "export_format": "icts-export-v1"}
    assert rows[1]["effective_month"] == rows[1]["hourly_rate_ils"] == rows[1]["availability"] == ""
    assert rows[1]["export_format"] == "icts-export-v1" and rows[1]["status"] == "INACTIVE"


@requires_db
def test_export_picks_version_for_month_else_next_future(world):
    client, uid, db = world
    w = insert_worker(db, valid_id(1), "Alice", "GENERAL_GUARD")
    insert_contract(db, w, uid, 1, date(2026, 1, 1), rate="40.00")
    insert_contract(db, w, uid, 2, date(2026, 9, 1), rate="41.00")
    insert_contract(db, w, uid, 3, date(2026, 9, 1), rate="42.00")  # same-month revision supersedes
    insert_contract(db, w, uid, 4, date(2027, 1, 1), rate="50.00")
    f = insert_worker(db, valid_id(2), "Future Only", "GENERAL_GUARD")
    insert_contract(db, f, uid, 1, date(2026, 11, 1), rate="60.00")
    insert_contract(db, f, uid, 2, date(2026, 12, 1), rate="61.00")
    by = lambda rows: {r["full_name"]: (r["effective_month"], r["hourly_rate_ils"]) for r in rows}  # noqa: E731
    assert by(parse(export(client))) == {"Alice": ("2026-09", "42.00"), "Future Only": ("2026-11", "60.00")}
    assert by(parse(export(client, "2026-08")))["Alice"] == ("2026-01", "40.00")
    assert by(parse(export(client, "2027-02")))["Alice"] == ("2027-01", "50.00")
    assert client.get("/api/exports/workers.csv?month=2026-13").status_code == 422


@requires_db
def test_only_full_name_can_start_with_a_trigger_character(world):
    client, uid, db = world
    for i, name in enumerate(TRICKY):
        w = insert_worker(db, valid_id(100 + i), name, ["GENERAL_GUARD", "SCREENER", "SUPERVISOR"][i % 3])
        insert_contract(db, w, uid)
    for r in parse(export(client)):
        for col, value in r.items():
            if col != "full_name":
                assert not value or value[0] not in TRIGGERS, (col, value)


@requires_db
def test_escape_written_in_file(world):
    client, uid, db = world
    for i, name in enumerate(["=x", "'Neil", "Neil"]):
        insert_worker(db, valid_id(100 + i), name)
    text = export(client).content.decode()
    assert ",'=x," in text and ",''Neil," in text and ",Neil," in text


@requires_db
def test_unmodified_export_reimports_as_all_unchanged(world):
    client, uid, db = world
    roles = ["GENERAL_GUARD", "SCREENER", "SUPERVISOR"]
    for i, name in enumerate(TRICKY):  # created directly, as the UI would store them
        w = insert_worker(db, valid_id(100 + i), name, roles[i % 3], "ACTIVE" if i % 2 else "INACTIVE")
        insert_contract(db, w, uid, effective_month=date(2026, 1 + i % 8, 1), rate=f"{40 + i}.25", min_hours=i, max_hours=100 + i,
                        availability=["MON:A", "WED:B", "SUN:C"] if i % 2 else ["TUE:A", "TUE:B", "TUE:C"])
    insert_worker(db, valid_id(300), "Worker Only")  # no contract at all
    fut = insert_worker(db, valid_id(301), "Future Only")
    insert_contract(db, fut, uid, 1, date(2026, 12, 1))
    rev = insert_worker(db, valid_id(302), "Revised")
    insert_contract(db, rev, uid, 1, date(2026, 9, 1), rate="40.00")
    insert_contract(db, rev, uid, 2, date(2026, 9, 1), rate="43.00")  # same-month revision

    for month in (None, "2026-03", "2027-06"):
        data = export(client, month).content
        prev = post_csv(client, data).json()
        assert prev["counts"] == {"new": 0, "changed": 0, "unchanged": len(TRICKY) + 3, "invalid": 0}, (month, [r for r in prev["rows"] if r["classification"] != "UNCHANGED"])
        assert all(r["export_row"] for r in prev["rows"])
    assert count(db, "contract_versions") == len(TRICKY) + 1 + 2


@requires_db
def test_names_from_external_files_and_ui_survive_export_and_reimport(world):
    client, uid, db = world
    external = ["'Neil", "'=x", "=cmd", "+1", "-2", "@s", "Neil"]
    ids = [valid_id(200 + i) for i in range(len(external))]
    ext = post_csv(client, csv_text(["national_id", "full_name", "role"], [[i, n, "guard"] for i, n in zip(ids, external)])).json()
    assert [r["full_name"] for r in ext["rows"]] == external  # verbatim: no apostrophe removed
    assert client.post(f"/api/imports/{ext['id']}/confirm", json={"decisions": {}}).status_code == 200
    ui = client.post("/api/workers", json={"national_id": valid_id(250), "full_name": "@ui", "role": "SCREENER"})
    assert ui.status_code == 201  # created in the UI

    data = export(client).content
    prev = post_csv(client, data).json()
    assert prev["counts"]["unchanged"] == len(external) + 1 and prev["counts"]["changed"] == 0
    assert sorted(r["full_name"] for r in prev["rows"]) == sorted(external + ["@ui"])
    # and a second full cycle is stable too
    assert post_csv(client, export(client).content).json()["counts"]["unchanged"] == len(external) + 1


@requires_db
def test_mixed_file_appended_external_rows_and_unknown_marker(world):
    client, uid, db = world
    w = insert_worker(db, valid_id(1), "=x")
    insert_contract(db, w, uid)
    data = export(client).content.decode("utf-8")
    extra = f"{valid_id(2)},'=y,SCREENER,ACTIVE,,,,,,\r\n{valid_id(3)},Bad,SCREENER,ACTIVE,,,,,,other\r\n"
    prev = post_csv(client, (data + extra).encode("utf-8")).json()
    rows = {r["national_id"]: r for r in prev["rows"]}
    assert rows[valid_id(1)]["classification"] == "UNCHANGED"
    assert rows[valid_id(2)]["classification"] == "NEW" and rows[valid_id(2)]["full_name"] == "'=y"  # external: verbatim
    assert rows[valid_id(3)]["classification"] == "INVALID" and rows[valid_id(3)]["errors"][0]["code"] == "UNKNOWN_EXPORT_FORMAT"
