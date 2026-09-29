# ICTS Europe Rostering System

A rostering tool for a security operation with three shifts a day (A 00:00-08:00, B 08:00-16:00, C 16:00-00:00) and three worker roles (General Guard, Screener, Supervisor). A planner imports workers and their contracts from CSV, generates a monthly roster with an OR-Tools CP-SAT engine, fixes gaps by hand (with ranked suggestions), and a manager signs the roster off. Estimated costs come from assigned hours and hourly rates.

- **Stack:** React + TypeScript + Vite, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, OR-Tools CP-SAT. One `docker compose up` runs everything.
- **Plan and decision log:** [`docs/plans/application.md`](docs/plans/application.md) (section numbers such as §4.4 below refer to it).
- **API reference:** [`backend/openapi.json`](backend/openapi.json).

Contents: [Quick start](#quick-start) - [Architecture](#architecture) - [Database schema](#database-schema-and-indexes) - [CSV format](#csv-format) - [Scheduling design](#scheduling-design) - [Benchmarks](#benchmarks) - [Features and their value](#features-and-their-value) - [Assumptions](#assumptions) - [Trade-offs and known limitations](#trade-offs-and-known-limitations) - [API overview](#api-overview) - [Tests](#tests)

## Quick start

Requirements: Docker with Compose v2. Nothing else is needed to run the system.

```
cp .env.example .env     # optional; only needed to change the defaults below
docker compose up --build
```

Open <http://localhost:8080>. The health check is <http://localhost:8080/api/health> (`{"status":"ok","engine":"ready"}`; `engine` becomes `ready` once the solver process has warmed up, a few seconds after start).

The backend applies the Alembic migrations, runs an idempotent seed and starts uvicorn by itself; there is no manual database step.

### Demo credentials (local demo use only)

| User | Password | Can do |
|---|---|---|
| `planner` | `planner-demo` | workers, contracts, CSV import/export, generate, save, edit rosters |
| `manager` | `manager-demo` | everything the planner can, plus approve and revoke approvals |

The passwords, the session secret and the database credentials come from environment variables. `docker-compose.yml` has demo defaults, so no `.env` is required; copying `.env.example` to `.env` (gitignored) is how you override them:

| Variable | Default | Meaning |
|---|---|---|
| `PLANNER_PASSWORD`, `MANAGER_PASSWORD` | `planner-demo`, `manager-demo` | passwords of the two seeded users |
| `SESSION_SECRET` | `dev-session-secret-change-me` in `.env.example` | signs the session cookie. If empty, the backend generates a random secret at start and logs a warning (sessions then reset on restart) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `icts`, `icts`, `icts` | database credentials, used by the `db` and `backend` services |
| `FRONTEND_PORT` | `8080` | host port of the web UI and the `/api` proxy |

The seed creates a missing user but never overwrites an existing one, so after changing a password reset the database (below).

### Load the sample workers

The stack starts with a small set of demo workers created by the seed, which is too few to fill a month. The 23-worker sample (9 General Guards, 9 Screeners, 5 Supervisors) is loaded through the Import page:

1. Log in as `planner`, open **Import** (`/imports`).
2. Choose `sample-data/workers.csv`, upload, and review the preview (23 rows, all NEW on a fresh database).
3. Click confirm. The sample workers are added next to the seeded ones.
4. Open **Roster**, pick a future month, click **Generate**, then **Save as draft**.

`sample-data/contract-changes-shortage.csv` (import it after `workers.csv`) lowers the supervisors' caps and availability so that a generated month has proven supervisor gaps; use it to see gap alerts and suggestions. See [`sample-data/README.md`](sample-data/README.md). To see how many workers exist:

```
docker compose exec db psql -U icts -c "select role, count(*) from workers group by role order by role"
```

### Reset

```
docker compose down -v     # removes the database volume
```

Use it after changing passwords in `.env`, or to get a clean database.

## Architecture

```
browser -> nginx (frontend container: serves the Vite build, proxies /api) -> FastAPI backend -> PostgreSQL
                                                                              |
                                                                              +-> process pool (1 spawned worker) running CP-SAT
```

```
docker-compose.yml   db (postgres:16, healthcheck) -> backend -> frontend
backend/
  app/main.py, config.py, db.py, errors.py, engine_pool.py, timeutil.py
  app/api_schemas/   Pydantic request/response models = the API contract
  app/auth/          users, signed session cookie, require_role()
  app/workers/       CRUD, Israeli national-ID checksum, status/role history
  app/contracts/     immutable versions, resolve(worker, month), availability helper
  app/changes/       change-set preview/apply, shared by UI edits and CSV import
  app/csvio/         parse, import preview/confirm, export
  app/rosters/       problem_builder, evaluation, generation, save, costs, edits, suggestions, approval
  app/scheduling/    the pure engine: standard library + ortools only, no database or web imports
  alembic/, tests/, bench/, openapi.json
frontend/            React, TypeScript, Vite, React Router, TanStack Query; API types generated from openapi.json
sample-data/         workers.csv, contract-changes-shortage.csv
tests/e2e/           httpx flows against the running stack
```

- **Engine isolation.** `app/scheduling/` has no database or framework dependency. `rosters/problem_builder` resolves contracts and builds its input; `rosters/evaluation` re-validates stored rosters with the same validator. Violations, gaps, shortfalls and costs are always computed on read from current data and never stored, so they cannot go stale.
- **Generation runs off the event loop.** The solve runs in a `ProcessPoolExecutor(max_workers=1)` with the `spawn` start method. The pool is warmed at startup (imports `ortools` and solves a one-variable model). If the child process dies, the failing request gets 500 `ENGINE_ERROR` and the pool is replaced under a lock (the next request works). One generation runs at a time; a second gets 429 `GENERATION_IN_PROGRESS`. Requests are synchronous: the response arrives after the solve, about the solver time limit at most plus overhead. CP-SAT uses `min(8, cpu_count)` workers.
- **Concurrency.** Every write that touches scheduling data first takes one transaction-scoped Postgres advisory lock, then checks optimistic versions (`row_version` / `expected_version`) and fingerprints; a mismatch is 409. Writes are serialised, which is fine for a single-site tool; reads and solving are not affected.
- **Time.** One helper, `now_israel()` (`Asia/Jerusalem`), decides the current month and which shifts have already started. The containers run on UTC.
- **Auth.** A signed HttpOnly, SameSite=Lax session cookie, same origin through nginx, JSON bodies only. Roles: `PLANNER` and `MANAGER`. (The worker role `SUPERVISOR` has nothing to do with app permissions.)
- **One error shape** for every non-2xx response: `{"error": {"code", "message", "details"}}`. Statuses: 400/401/403/404; 409 `VERSION_CONFLICT`, `STALE_PREVIEW`, `ALREADY_CONFIRMED`, `WORKER_IN_USE`, `APPROVED_EDIT_NOT_ACKNOWLEDGED`, `ALREADY_APPROVED`, `NOT_APPROVED`; 413 `FILE_TOO_LARGE`, `TOO_MANY_ROWS`; 415; 422 (validation, `HARD_VIOLATIONS` with the violation list, `LOCKED_SHIFT`, `WARNINGS_NOT_ACKNOWLEDGED`); 429 `GENERATION_IN_PROGRESS`; 500 `ENGINE_ERROR`.

## Database schema and indexes

Defined in `backend/alembic/versions/` (an initial schema migration plus one that adds the `MANUAL` revoke cause) and mirrored by the models in `backend/app/*/models.py`.

| Table | Columns (main) | Constraints and indexes |
|---|---|---|
| `users` | id, username, display_name, password_hash, app_role | username UNIQUE; CHECK app_role IN (PLANNER, MANAGER) |
| `workers` | id, national_id (text), full_name, role, status, row_version, created_at, updated_at | national_id UNIQUE; CHECK `national_id ~ '^[0-9]{9}$'` (the Israeli checksum is enforced in the application); CHECK role, status; index `ix_workers_status_role (status, role)` |
| `contract_versions` | id, worker_id, version_no, effective_month (date), hourly_rate_ils numeric(10,2), min_hours, max_hours, availability jsonb (`["MON:A", ...]`), created_at, created_by, source (UI, CSV), import_id | FK worker RESTRICT; UNIQUE (worker_id, version_no); CHECK day of effective_month = 1, `0 <= min <= max <= 744`, rate > 0; index `ix_contract_versions_worker_effective_version (worker_id, effective_month DESC, version_no DESC)`; **trigger `reject_update_delete`: rows are insert-only** |
| `csv_imports` | id, created_by, created_at, status (PENDING, CONFIRMED), preview jsonb, result jsonb, confirmed_at, confirmed_by | CHECK status |
| `rosters` | id, month (date), status (DRAFT, APPROVED), forbid_adjacent_shifts bool default false, row_version, generation_meta jsonb, updated_at, updated_by | month UNIQUE (`uq_rosters_month`); CHECK day of month = 1; CHECK status |
| `roster_assignments` | id, roster_id, worker_id, date, shift, role (the slot role, snapshotted) | FK roster CASCADE, FK worker RESTRICT; UNIQUE (roster_id, worker_id, date, shift); indexes `(roster_id, date, shift)` and `(worker_id)` |
| `roster_approvals` | id, roster_id, roster_version, approved_by, approved_at, acknowledged_warnings jsonb, reason, revoked_at, revoked_by, revoke_cause, revoke_ref | FK roster CASCADE; CHECK revoke_cause IN (EDIT, REGENERATE, CONTRACT_CHANGE, WORKER_CHANGE, MANUAL) or NULL; index `ix_roster_approvals_roster_approved_at (roster_id, approved_at DESC)` |
| `worker_field_history` | id, worker_id, field (STATUS, ROLE), old_value, new_value, effective_at, changed_by | FK worker RESTRICT; index `(worker_id, field, effective_at DESC)`; **insert-only trigger**, like `contract_versions` |

Design points:

- **Contract versions are immutable.** A change creates a new version. For a month M the applicable contract is the row with the greatest `effective_month <= M`, ties broken by the highest `version_no`. So a future version never applies to an earlier month, and a same-month correction supersedes the earlier row while both stay in the history. The DB trigger enforces immutability, not just the application. Identical data creates no version.
- **Worker status/role history.** Every status or role change adds a `worker_field_history` row. Shifts that have already started are checked against the worker's status and role *as of the shift start*, so deactivating a worker mid-month never turns a shift already worked into a violation. Upcoming shifts always use the current worker row.
- **Assignments snapshot the slot role.** A later role change shows up as a `WRONG_ROLE` violation on upcoming shifts instead of silently moving anyone.
- **Approvals are history rows**, not a flag: an approval that is revoked keeps its row with who/when/why (audit trail, see below).

## CSV format

Import: `POST /api/imports` with a raw `text/csv` body (any other content type is 415), or the Import page. Export: `GET /api/exports/workers.csv?month=YYYY-MM`, or the export control on the Import page.

- **Encoding:** UTF-8; a BOM is accepted on import and written on export (Hebrew names in Excel).
- **Columns are matched by header name, in any order.** A header row is required. Headers are trimmed, lowercased, and spaces/hyphens become `_`.
- **Required always:** `national_id`, `full_name`, `role`. **Optional:** `status` (empty or missing = ACTIVE), `effective_month` (`YYYY-MM`; empty or missing = the current Israel month, shown resolved in the preview), `export_format`.
- **Contract columns** are `hourly_rate_ils`, `min_monthly_hours`, `max_monthly_hours` and availability. They are required together: a row where all are empty is a valid *worker-only* row (creates or updates the worker, no contract version); a row where some are filled is INVALID `INCOMPLETE_CONTRACT`.
- **Missing required column:** 400 `MISSING_COLUMNS` with the list. Two headers that normalise to the same name: 400 `DUPLICATE_COLUMN`. Unknown columns are ignored and listed as a warning in the preview.

Header aliases (also served by `GET /api/meta`):

| Column | Aliases |
|---|---|
| `national_id` | `id`, `israeli_id`, `id_number` |
| `full_name` | `name` |
| `hourly_rate_ils` | `hourly_rate`, `hourly_cost` |
| `min_monthly_hours` | `min_hours` |
| `max_monthly_hours` | `max_hours` |
| `available_days` | `days` |
| `available_shifts` | `shifts` |

Value aliases (case-insensitive; spaces, hyphens and underscores are equal): role `General Guard` / `general-guard` / `GENERAL_GUARD` / `Guard` = GENERAL_GUARD, `Screener` = SCREENER, `Supervisor` = SUPERVISOR; status `Active`, `Inactive`.

**Availability, exactly one form per row** (both normalise to the same set of day/shift pairs, so classification does not depend on the form):

- *Per-day form:* `availability` = `MON:AB|TUE:ABC|FRI:C`. Available only for the listed pairs.
- *Brief form:* `available_days` + `available_shifts`. Available for **every listed shift on every listed day** (cross product), for example `Sun|Mon` and `A|C` give 4 pairs. Days are `Sun`...`Sat` or full names; shifts are `A`/`B`/`C` or `Morning`/`Day`/`Evening`, and letters may be run together (`AC`). Tokens are separated by `|` or `;`, or by `,` inside a quoted field.
- Both forms filled: INVALID `AMBIGUOUS_AVAILABILITY`; only days or only shifts: `INCOMPLETE_AVAILABILITY`; nothing usable: `MISSING_AVAILABILITY`; an unknown token: INVALID naming the token.
- Export always writes the lossless per-day form.

**National IDs are strings.** They are trimmed and must be exactly 9 digits with a valid Israeli ID checksum. Nothing is padded: an 8-digit ID is INVALID `ID_LENGTH` ("spreadsheets often drop leading zeros"), scientific notation (`1.23E+08`) is `ID_FORMAT`, and a leading zero (`012345674`) is preserved. A duplicated ID inside one file makes every row with that ID INVALID `DUPLICATE_IN_FILE`; other rows are unaffected.

**Preview then confirm.** The upload returns a preview: each row is NEW, UNCHANGED, CHANGED or INVALID with field diffs, the resolved effective month, the affected rosters, whether an approved roster would be invalidated (`invalidates_approved`) and, for retroactive changes, `locked_violations` (new hard violations in shifts that have already started, which editing cannot fix). Nothing is applied until `POST /api/imports/{id}/confirm` with optional per-row `APPROVE`/`SKIP` decisions. Confirm is one transaction; invalid and skipped rows are never applied and do not block valid ones. A second confirm is 409 `ALREADY_CONFIRMED`; if the data moved since the preview it is 409 `STALE_PREVIEW` with a fresh preview and nothing is applied.

**Export and the round-trip marker.** Export has one row per worker with the contract effective for the chosen month (default: the current Israel month), otherwise the next future version; workers with no applicable contract are still exported with empty contract columns and counted separately (response header `X-No-Contract-Count`; `X-Worker-Count` is the total). Re-importing an unmodified export gives all rows UNCHANGED (checked in the e2e suite).

`full_name` is the only free-text field, so it is protected against spreadsheet formula injection with a convention that round-trips exactly:

- Every exported row carries `export_format=icts-export-v1`.
- **Export** writes one leading apostrophe `'` before any name that starts with `=`, `+`, `-`, `@`, TAB, CR or `'`.
- **Import** decides per row by that marker. *External rows* (no `export_format` column, or an empty value) are taken **verbatim**: an apostrophe is never treated as an escape, so `'Neil` and `'=x` are stored exactly as written. *Export rows* (`icts-export-v1`) are unescaped: if the name starts with `'` and its second character is one of the trigger characters, that first `'` is dropped; otherwise it is kept. Any other marker value is INVALID `UNKNOWN_EXPORT_FORMAT`.
- So `import(export(x)) = x` for every name. This guarantee covers the file as exported; if a spreadsheet application re-saves the file, cell types and quoting are outside our control.

**Limits:** 1 MB (1,048,576 bytes) and 5,000 data rows per file. The byte limit is enforced while streaming the request body (413 `FILE_TOO_LARGE`, and an oversized `Content-Length` is refused before reading); the row limit while parsing (413 `TOO_MANY_ROWS`, nothing stored). Invalid UTF-8 is 400 `INVALID_ENCODING`. nginx also caps bodies at 2 MB as an outer backstop.

## Scheduling design

The engine (`backend/app/scheduling/`) is pure Python on CP-SAT. It is given a `Problem` (month, demand, workers with contracts already resolved for that month, `free_from`, fixed and neighbour assignments, the adjacency flag) and returns one of `Solved`, `NoSolutionWithinLimit`, `InvalidInput` or `EngineError`.

**Demand and rules from the brief.** Default demand is 2 General Guard, 2 Screener and 1 Supervisor per shift (15 slots a day), held in one constant. Hard constraints: availability, role, at most 2 shifts per worker per calendar day, at most `max_hours` per month (a shift is 8 hours), no overstaffing. No labour-law rules are simulated. Coverage (demand) and minimum hours are **soft**: with too few workers the engine returns a partial roster with the gaps and shortfalls flagged instead of failing, so "zero new assignments" is always feasible.

**Single weighted objective with a lexicographic optimum.** Terms, over active workers and free slots: `uncovered[d,s,r]` (missing workers in a slot) and `short[w]` (hours below the worker's minimum, capped at `min_hours`). The engine minimises

```
W * sum(uncovered) + sum(short)        with   S_max = sum(min_hours of active workers),  W = S_max + 1
```

*Why this is lexicographic (coverage first, then minimum hours).* Because each `short[w] <= min_hours_w`, every feasible solution has `0 <= sum(short) <= S_max < W`. If roster P leaves at least one fewer slot uncovered than roster Q, then `obj(P) <= W*(U_Q - 1) + S_max < W*U_Q <= obj(Q)`. So no amount of hour shortfall can ever buy a covered slot: an optimal solution has the fewest gaps, and among those the smallest total shortfall. Input validation rejects instances where `W * slots + S_max` would exceed 2^53, so objective values stay exact in a double (real data is around 3 million). Cost is **not** in the objective: estimated costs are displayed, cheaper workers are never preferred.

**Optional adjacency rule (off by default).** The brief's only hard scheduling rule beyond contracts is the daily limit of 2. A per-roster setting, "forbid back-to-back shifts", additionally forbids A then B, B then C on the same day, and C then the next day's A (A+C on the same day stays allowed). It is **off by default, so the defaults enforce exactly the brief's rules**; it is an optional product setting, not a claim of labour-law compliance. It is stored on the roster, applies to generation, manual edits, suggestions and the validator, and is checked across month boundaries when either month's roster has it on.

**Locked and free shifts.** In the current month, shifts that have already started (Israel time) are immutable history: regeneration keeps them as fixed assignments and reschedules only future shifts. Fixed assignments may break the *current* data (for example after a retroactive contract change); such violations stay visible and are never "repaired", but new assignments may not introduce a new violation or worsen one (compared by key and magnitude, not by counts). Every roster the engine returns passes an independent validator gate, and all reported metrics are recomputed from the returned roster, never taken from solver values.

**Reporting honestly under the time limit.** Solver status is reported as it is. OPTIMAL means both the coverage and the minimum-hours level are proven. FEASIBLE (time limit hit with a solution) reports a coverage **lower bound** derived as `LB = max(0, ceil((B - S_max) / W))` from the solver's objective bound `B` (rounded conservatively), combined by `max` with a cheap proven diagnostic bound (per-slot and per-role capacity deficits). The UI says "at least L upcoming positions cannot be filled" only when that bound is positive. No solution within the limit is `NoSolutionWithinLimit` (not a claim of infeasibility, and nothing is replaced or saved). Suspected causes of a gap are labelled `SUSPECTED` and are explanations only; they never feed a bound.

**Timeout limitations (please read).**

- The time limit (`time_limit_s`, default 10 s, `SOLVER_TIME_LIMIT_S` in the backend environment; it is not passed through `docker-compose.yml`, so change it there if needed) bounds CP-SAT *search* time. It is not an end-to-end response deadline: model building, validation and the HTTP round trip come on top (see the benchmarks: at 1,000 workers model building alone took about 7 s).
- At FEASIBLE there is **no bound on the hour shortfall**: "minimum hours not proven optimal within the time limit" is all that can be said. The coverage bound is only as strong as CP-SAT's objective bound; a loose bound can give 0 even when gaps are unavoidable (the diagnostic bound is the fallback).
- Because `W` is large, the raw objective gap looks large; the UI shows only derived values.

**Costs are core estimates.** Estimated cost of an assignment is 8 h x the hourly rate of the worker's contract resolved for the roster's month, shown per shift, per worker and as a monthly total, computed in `Decimal` and rounded to 0.01 ILS for display. Premiums (night, weekend, overtime) are not modelled; assignments of workers without an applicable contract are excluded and counted as "cost unknown".

## Benchmarks

Measured for real with `backend/bench/` (the actual model: weighted objective, fixed and neighbour assignments, adjacency rule off and on), nothing copied.

- **Hardware:** Apple M3 Max, 14 cores, 36 GB RAM, macOS (Darwin 25.6.0); run natively with Python 3.14.6 and OR-Tools 9.15.6755.
- **Time budget:** every run uses the default `time_limit_s = 10`; the scale runs are repeated at `time_limit_s = 60`. `num_workers = 8`, `random_seed = 0`. `total_s` is validation + diagnostics + model build + search + result validation.
- **Reproduce** (from `backend/`, with the dev dependencies installed):

```
python -m bench.run small --time-limits 10
python -m bench.run scale --sizes 200 500 1000 --time-limits 10
python -m bench.run scale --sizes 200 500 1000 --time-limits 60
```

`status` is OPTIMAL when the roster is lexicographically optimal, FEASIBLE otherwise. `coverage lower bound` equals `total_uncovered` in every run (gap 0), i.e. the coverage level is proven even when the status is FEASIBLE.

### Small fixtures (30/31-day months, 10 s)

Seeded generator: comfortable (~40 workers), tight (capacity about equal to demand), too few supervisors, fragmented (sparse availability), min-hours pressure, inactive workers, mid-month (`free_from` on day 15 shift B with fixed assignments), retroactive conflict (fixed assignments over a reduced cap), neighbour months.

| fixture | workers | rule off: status / uncovered / shortfall h / total s | rule on: status / uncovered / shortfall h / total s |
|---|---|---|---|
| comfortable | 40 | OPTIMAL / 0 / 280 / 0.58 | OPTIMAL / 0 / 280 / 0.40 |
| tight | 20 | OPTIMAL / 305 / 0 / 0.15 | OPTIMAL / 305 / 0 / 0.10 |
| short supervisors | 33 | OPTIMAL / 68 / 0 / 0.21 | OPTIMAL / 68 / 0 / 0.19 |
| fragmented | 60 | OPTIMAL / 4 / 0 / 0.05 | OPTIMAL / 4 / 0 / 0.06 |
| min-hours pressure | 40 | OPTIMAL / 0 / 3200 / 0.46 | OPTIMAL / 0 / 3200 / 0.23 |
| with inactive workers | 50 | OPTIMAL / 0 / 160 / 0.42 | OPTIMAL / 0 / 160 / 0.23 |
| mid-month | 40 | OPTIMAL / 145 / 920 / 0.25 | OPTIMAL / 145 / 920 / 0.41 |
| retroactive conflict | 40 | OPTIMAL / 132 / 0 / 0.18 | OPTIMAL / 132 / 0 / 0.19 |
| neighbour months | 40 | OPTIMAL / 0 / 0 / 0.38 | OPTIMAL / 0 / 0 / 0.22 |

All 18 small runs are OPTIMAL in under 0.6 s. (On the retroactive-conflict fixture the diagnostic bound is 6 while the true minimum is 132; the solver's own bound is tight, so the reported lower bound is 132.)

### Scale fixtures (31-day month)

`comfortable_ratio` scales demand by `k = round(n/40)` to keep the comfortable staffing ratio (several sites' worth of demand); `default_demand` keeps demand at 15 slots a day whatever `n` (a large pool against small demand); `mid_month` is the comfortable ratio with `free_from` on day 15 shift B.

| fixture | workers | 10 s: status / shortfall h / model build s / search s / total s | 60 s: status / shortfall h / model build s / search s / total s |
|---|---|---|---|
| comfortable_ratio | 200 | OPTIMAL / 1400 / 0.49 / 2.70 / 3.27 | OPTIMAL / 1400 / 0.50 / 2.66 / 3.24 |
| default_demand | 200 | OPTIMAL / 16280 / 0.50 / 1.82 / 2.39 | OPTIMAL / 16280 / 0.50 / 1.80 / 2.38 |
| mid_month | 200 | OPTIMAL / 9500 / 0.35 / 0.95 / 1.75 | OPTIMAL / 9500 / 0.37 / 0.95 / 1.77 |
| comfortable_ratio | 500 | **FEASIBLE** / 7064 / 2.10 / 10.20 / 12.51 | **FEASIBLE** / 5408 / 2.10 / 60.25 / 62.56 |
| default_demand | 500 | OPTIMAL / 46280 / 2.06 / 4.57 / 6.81 | OPTIMAL / 46280 / 2.09 / 4.55 / 6.81 |
| mid_month | 500 | OPTIMAL / 25500 / 1.36 / 3.59 / 6.10 | OPTIMAL / 25500 / 1.34 / 3.52 / 5.97 |
| comfortable_ratio | 1000 | **FEASIBLE** / 19332 / 7.27 / 10.43 / 18.16 | **FEASIBLE** / 7384 / 7.06 / 60.34 / 67.84 |
| default_demand | 1000 | OPTIMAL / 96280 / 7.12 / 9.99 / 17.47 | OPTIMAL / 96280 / 7.08 / 9.99 / 17.41 |
| mid_month | 1000 | **FEASIBLE** / 49840 / 4.31 / 10.20 / 16.85 | OPTIMAL / 49500 / 4.28 / 12.98 / 19.49 |

Total uncovered is 0 for every `comfortable_ratio` and `default_demand` run, and equals the proven lower bound (1005 / 2510 / 5305) for `mid_month` (its locked part is already in the past).

What this shows, honestly:

- **Coverage is always solved and proven, quickly.** The FEASIBLE runs are FEASIBLE only because the *minimum-hours* term is not proven optimal within the limit; more time helps (shortfall 19332 -> 7384 h at 1,000 workers, 7064 -> 5408 h at 500) but does not reach a proof at 60 s.
- **The default limit of 10 s is enough for coverage optimality up to 1,000 workers**, and every result within 200 workers is proven optimal in about 3 s. Above that, expect a good but not proven-optimal minimum-hours result at 10 s. Model building is not covered by the limit (7 s at 1,000 workers), so end-to-end time was up to about 1.8 times the limit at 1,000 workers (18 s against 10 s).
- The dockerised backend sees the Docker VM's CPUs (2 on the machine above), not the 14 cores; `num_workers = min(8, cpu_count)` adapts, but the largest instances will be slower there than in the table. On the compose stack, generating a month for the 28 workers of the sample setup (5 seeded + 23 imported) took about 0.14 s per request (OPTIMAL, 0 gaps, 0 shortfall, adjacency rule off and on).

## Features and their value

**Core (from the brief):** worker CRUD with ID validation; immutable, versioned contracts with month resolution; CSV import (preview, partial success, confirm) and export; roster generation with gap and shortfall alerts before saving; a day-by-shift grid; manual add/remove/move under a repair rule; estimated costs; sample data; `docker compose up`.

**Bonus feature 1: manager approval with automatic invalidation and an audit trail.** *Rationale:* a roster that goes live should have a named person's sign-off, and a signed-off roster must never silently stop being valid. A manager approves a draft (planners get 403). Soft shortages (coverage gaps, minimum-hour shortfalls) may be approved only with an explicit acknowledgement, a reason and the fingerprint of the exact shortages the manager saw (a changed list is 409 `STALE_PREVIEW`); **hard violations can never be acknowledged** and block approval with 422 `HARD_VIOLATIONS`. Any later change that would invalidate the roster revokes the approval automatically and returns it to draft: a manual edit (`EDIT`), regeneration (`REGENERATE`), a contract change by UI or CSV that creates hard violations (`CONTRACT_CHANGE`, referencing `contract_version:{id}` or `import:{id}`), or a worker status/role change (`WORKER_CHANGE`, `worker:{id}`); a manager can also revoke by hand (`MANUAL`). Editing an approved roster asks for an explicit acknowledgement first. The audit trail is the approval history on the roster: every approval and revocation, in order, with actor, time, roster version, reason, the acknowledged-shortage snapshot, and revoke cause and reference. It covers approval events; it is not a log of every edit.

**Bonus feature 2: gap-fill suggestions with reasons.** *Rationale:* "shift X cannot be filled" is only useful with a way to fix it. For any open (upcoming) slot the planner gets ranked candidates, each with human-readable reasons (for example "Screener - available Tue B - 96/160 h (64 h below minimum) - 1 shift that day"), and applies one in a click. A candidate must be an active, contracted worker of the right role whose addition introduces no new or worse hard violation (including the adjacency rule where it applies). Ranking is by minimum-hours deficit (largest first), then assigned hours (fewest first), then name, so the people furthest below their contracted minimum are offered first. Applying is the ordinary add endpoint, re-validated. There are no solver calls, swap chains or cost-based ranking. This goes beyond the mandatory manual add: it finds and explains the candidates.

## Assumptions

- Shift `A` 00:00-08:00, `B` 08:00-16:00, `C` 16:00-00:00 belong to their start date and count as 8 hours each. Demand is the same every day: 2 General Guard, 2 Screener, 1 Supervisor per shift (a fixed staffing ratio, confirmed as acceptable).
- Incomplete rosters are allowed and flagged rather than refused; handling duplicates in a CSV (whole file's rows with that ID become INVALID) is our decision.
- The current month and "already started" are decided in `Asia/Jerusalem` time. Rosters of months before the current one are read-only history (not revalidated, edited, regenerated or approved). Started shifts of the current month are immutable.
- Contracts are month-versioned; a version with a past effective month is allowed and labelled retroactive, with the consequences previewed before it is applied.
- A worker's status and role are not month-versioned; changes are recorded with a timestamp and affect upcoming shifts immediately.
- A worker with no applicable contract for a month is excluded from generation and suggestions and flagged (`NO_CONTRACT_FOR_MONTH` on existing assignments).
- Hourly rate is a single number per contract version; no premiums.
- Approval and CSV import expiry are not modelled. A local demo, no public deployment; the demo credentials are only for local use.

## Trade-offs and known limitations

Trade-offs:

- **One weighted solve instead of two phases.** Simpler, one model, and a proven lexicographic optimum when it finishes; not assumed faster than two phases. Its weakness is the unproven minimum-hours term on very large instances (see benchmarks).
- **Synchronous generation with a single solver process and a global write lock.** Simple and correct for one site and a few users; not built for many concurrent planners. No job queue.
- **Violations, gaps and costs computed on read** rather than stored: always current, at the cost of recomputation per request.
- **Optimistic concurrency with fingerprints** (409 on stale data) rather than locking the UI.

Known limitations (found and left as is; none blocks the flows above):

- **A cancelled generate request keeps solving.** Cancelling the HTTP request releases the busy guard, but the spawned solve keeps running; the next generation queues behind it on the single worker process for up to the solver time limit.
- **Engine warm-up is not retried.** If the startup warm-up fails, `/api/health` stays `engine: not_ready` until a pool crash replaces the executor (requests still try to solve).
- **The database session stays open during the solve**, holding one pooled connection for up to the time limit. Only one generation runs at a time, so the pool cannot be exhausted.
- **`MANUAL` revoke stores no reason** (the revoke endpoint takes only `expected_version`); the audit row records who and when.
- **A CSV preview is stored whole as JSONB** in `csv_imports`; a 5,000-row import makes a large document. Fine for a demo; imports are never expired or cleaned up.
- **Mock API (`VITE_API_MOCK=1`)** covers only login and the roster routes; imports, approval, edits and workers need the real backend.
- **Approving the current month needs an acknowledgement** if any started shift was left unfilled: those past shortages are counted as soft shortages ("past" gaps) even though they cannot be fixed.
- The detailed impact preview for worker role/status changes is deferred (the UI asks for a plain confirmation). The month picker resets to the current month on page reload. There is no API test for revoking on a history month and no component tests for the approval panel and import page (covered by manual browser runs).
- Seed and sample workers coexist: importing the sample adds 23 workers to the seeded ones (no auto-load of the sample, because `sample-data/` is not copied into the backend image).
- Israeli national-ID checksum is validated in the application, not in the database.

## API overview

Everything is under `/api` and needs a session cookie except login and health. The full, typed reference is [`backend/openapi.json`](backend/openapi.json) (regenerate with `python scripts/export_openapi.py`; a test fails when it is stale); the frontend's TypeScript types are generated from it (`npm run generate-types`).

| Area | Endpoints |
|---|---|
| Health, meta | `GET /health`, `GET /meta` (shifts, roles, default demand, CSV aliases) |
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| Workers | `GET, POST /workers`, `GET, PATCH, DELETE /workers/{id}` (PATCH of role/status needs `expected_version`; delete is 409 `WORKER_IN_USE` when history exists) |
| Contracts | `GET /workers/{id}/contracts?resolved_for=YYYY-MM`, `POST /workers/{id}/contracts/preview`, `POST /workers/{id}/contracts` (with the preview fingerprint) |
| CSV | `POST /imports` (raw `text/csv`), `GET /imports/{id}`, `POST /imports/{id}/confirm`, `GET /exports/workers.csv?month=` |
| Rosters | `GET /rosters/{month}`, `POST /rosters/{month}/generate` (`{forbid_adjacent_shifts}`; persists nothing), `POST /rosters/{month}/save` (fingerprint, `expected_version`, `replace_existing`) |
| Edits | `GET, POST /rosters/{month}/assignments`, `DELETE /rosters/{month}/assignments/{id}`, `POST .../{id}/move`, `GET /rosters/{month}/suggestions?date=&shift=&role=` |
| Approval | `GET /rosters/{month}/approval-preview`, `POST /rosters/{month}/approve` (manager), `POST /rosters/{month}/revoke` (manager) |

`{month}` is `YYYY-MM`. `GET /rosters/{month}` returns the assignments, violations, coverage gaps, hour shortfalls, estimated costs, `free_from`, `forbid_adjacent_shifts` and the approval history.

## Tests

**Backend (pytest).** Needs a Postgres reachable through `TEST_DATABASE_URL` (tests that need the database skip when it is unreachable). The compose `db` service publishes no host port, so use a throwaway Postgres for the tests:

```
docker run -d --name icts-test-pg -e POSTGRES_USER=icts -e POSTGRES_PASSWORD=icts -e POSTGRES_DB=icts -p 55432:5432 postgres:16
cd backend
python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
TEST_DATABASE_URL=postgresql://icts:icts@localhost:55432/icts PYTHONPATH=. pytest
```

The suite migrates the database itself and rolls each test back; it needs Python 3.11 or newer. The engine tests and the benchmark runner need no database.

**Frontend.**

```
cd frontend
npm ci
npm run typecheck && npm run lint && npm test && npm run build
```

`npm run dev` starts Vite on port 5173 and proxies `/api` to `localhost:8000`; `VITE_API_MOCK=1 npm run dev` serves the login and roster routes from an in-browser mock.

**End-to-end (`tests/e2e/`).** httpx flows against the running stack: login as planner and manager (403 for a planner on approve); import the sample CSV (preview, then confirm); export and re-import as all UNCHANGED; generate a future month, save as draft, read back; approve as manager; edit an approved roster and see the automatic revoke with cause `EDIT`; suggestions for the resulting gap and one-click apply; a contract change through the API revoking an approval with `CONTRACT_CHANGE`; a CSV import doing the same with reference `import:{id}`; and the error shapes (hard violation with its violation list, stale version, stale fingerprint, wrong content type, missing columns).

```
docker compose down -v && docker compose up -d --build     # clean stack on :8080
pip install pytest httpx                                     # or use the backend venv
pytest tests/e2e -v                                          # E2E_BASE_URL defaults to http://localhost:8080
```

To keep it away from any other running stack, use a separate project name and port:

```
FRONTEND_PORT=18080 docker compose -p t9 up -d --build
E2E_BASE_URL=http://localhost:18080 pytest tests/e2e -v
docker compose -p t9 down -v
```

If the stack is unreachable the whole suite is skipped with a message saying how to start it. Other variables: `PLANNER_PASSWORD` and `MANAGER_PASSWORD` if you changed them. The flows are ordered and share state, so run the file as a whole. They can be repeated on the same database: each run leaves its rosters behind (there is no delete endpoint), so the next run picks the first future months, starting two months ahead of the current Israel month, that hold no roster yet (it needs a free block of five consecutive months and fails with a clear message when none is left within five years; `docker compose down -v` resets everything). The sample import is also repeatable: on a database that already has the sample workers its rows are UNCHANGED instead of NEW.
