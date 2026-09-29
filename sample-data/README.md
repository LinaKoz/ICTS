# Sample data

| File | What it is |
|---|---|
| `workers.csv` | 23 workers (9 General Guard, 9 Screener, 5 Supervisor) with contracts. Every 28-, 30- and 31-day month can be generated from it with 0 coverage gaps and 0 hour shortfalls, with the optional back-to-back rule off and on (checked by `backend/tests/csvio/test_sample_data.py`). |
| `contract-changes-shortage.csv` | Contract changes for the 5 supervisors (lower monthly caps, narrower availability, and nobody available on Saturdays). Import `workers.csv` first, then this file: the 5 rows are CHANGED, and a generated month then has proven supervisor gaps (the coverage lower bound equals the gap count: 30 in a 28-day month, 36 in 30 days, 39 in 31 days) and no gaps in other roles. |

Import them on the Import page (or `POST /api/imports` with `Content-Type: text/csv`, then `POST /api/imports/{id}/confirm`).

Conventions used in the files (full format in the README of the repository, P14):
- `effective_month` is left empty, so the contract applies from the current Israel month at import time. Importing the shortage file in the same month supersedes the first contract (same-month revision), and both versions are kept.
- Availability uses both forms, one per row: `available_days` + `available_shifts` (cross product) or the per-day `availability` (`MON:ABC|FRI:AB`).
- National IDs are strings; `012345674` keeps its leading zero.
