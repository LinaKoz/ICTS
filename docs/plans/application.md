# ICTS Europe Rostering System: plan

Single merged plan covering the application and the scheduling engine.

**Deadline:** 2026-10-01 14:00 Asia/Jerusalem. Delivered via GitHub; not deployed publicly.
**Stack:**
- Frontend: React + TypeScript + Vite
- Backend: FastAPI (Python), SQLAlchemy 2, Alembic
- Database: PostgreSQL
- Scheduling: OR-Tools CP-SAT
- Runs with a single `docker compose up`

## 1. Employer clarifications vs. our choices
| Source | Item |
|---|---|
| Danny (confirmed) | Fixed staffing is acceptable if the ratio between roles is reasonable |
| Danny (confirmed) | Handling incomplete rosters is our decision |
| Danny (confirmed) | Must respect personal constraints (contracts) and global constraints (demand, daily limit) |
| Danny (confirmed) | Duplicate-worker behaviour in the CSV is our decision |
| Our choice | Demand of 2 GENERAL_GUARD, 2 SCREENER and 1 SUPERVISOR per shift |
| Our choice | Partial rosters come back with gaps and shortfalls flagged |
| Our choice | CP-SAT engine with a single weighted objective (§4) |
| Our choice | All policies in §5 marked "proposed" |
| Brief | The only hard scheduling rule beyond contracts is at most 2 shifts per calendar day; no labour laws are simulated |
| Our choice (optional setting) | A per-roster setting, **off by default**, forbids back-to-back shifts: A→B, B→C, and C→next-day A. A+C on the same day stays allowed. With the setting off, the engine enforces exactly the brief's rules. It is an optional product setting, not a claim of labour-law compliance |
| Brief ("hourly cost… used for cost estimation") | Estimated costs are core scope, not a bonus feature |
| Our choice (D7) | Bonus features: (1) manager approval with automatic invalidation and an audit trail, (2) gap-fill suggestions with reasons |
| Our choice | Regenerating the current month keeps shifts that have already started (Asia/Jerusalem time); only future shifts are rescheduled |
| Our choice | Estimated shift and monthly costs are displayed from assigned hours and hourly rates. Cost is not part of the solver objective |

## 2. Architecture
```
docker-compose.yml   db (postgres:16, healthcheck) → backend → frontend (nginx serves build, proxies /api)
backend/  FastAPI, SQLAlchemy 2, Alembic, ortools, pytest
  app/main.py, config.py, db.py, errors.py
  app/api_schemas/ Pydantic request/response models: the shared API contract (§6)
  app/auth/        users, session cookie, require_role()
  app/workers/     CRUD, national-ID validation
  app/contracts/   versions, resolve(worker, month)
  app/changes/     change-set preview/apply (shared by UI edits and CSV)
  app/csvio/       parse, import preview/confirm, export
  app/rosters/     problem_builder, evaluation, generation, save, costs, edits, suggestions, approval
  app/scheduling/  pure engine (§4): stdlib + ortools only
  alembic/, tests/, bench/
frontend/  React, TypeScript, Vite, React Router, TanStack Query; API types generated from OpenAPI
sample-data/  workers.csv, contract-changes-shortage.csv
```
- **Startup:**
  - The backend entrypoint runs `alembic upgrade head`, then an idempotent seed, then uvicorn (one worker).
  - The seed creates the demo users. If the workers table is empty, it also loads the sample workers and contracts, so the vertical slice (§8) works on first start.
  - `docker compose up` needs no manual database step.
- **Configuration and demo credentials (D4):**
  - `docker-compose.yml` passes `PLANNER_PASSWORD`, `MANAGER_PASSWORD` and `SESSION_SECRET` to the backend.
    - The passwords use Compose interpolation with demo defaults (`${PLANNER_PASSWORD:-…}`), so `docker compose up` works with no preparation.
  - `.env.example` lists the same variables with the same demo values. Copying it to `.env` (which is gitignored) and editing it is optional, and is how the defaults are overridden.
  - If `SESSION_SECRET` is empty, the backend generates a random secret at startup and logs a warning. Sessions then reset on restart. No secret is hardcoded.
  - The seed creates missing users only; it never overwrites a password. After changing passwords in `.env`, reset with `docker compose down -v`. The README documents this.
  - The README lists the demo credentials and states that they are for local demo use only.
- **Generation execution:**
  - The engine runs in a `ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))` via `run_in_executor`, so CPU work never blocks the API event loop or other requests.
    - `spawn` avoids forking a process that holds the event loop, database connections and threads.
  - **Warm-up:** at startup, the app lifespan submits `_warm_up()` to the pool.
    - In the child, `_warm_up()` imports `ortools.sat.python.cp_model` and solves a one-variable model, so both the import and the native solver are exercised.
    - A warm-up failure is logged, and `/api/health` reports `engine: not_ready`. Requests still try.
  - **Pool ownership:** one `EnginePool` object holds the current executor and an `asyncio.Lock`.
    - On `BrokenProcessPool` (the child crashed or was OOM-killed), the failing call enters the lock. It replaces the executor only if the current one is still the executor that failed; a caller that finds a newer executor skips the replacement.
    - Replacement shuts the old executor down (`wait=False, cancel_futures=True`), creates a new one and warms it up.
    - So concurrent failures can never create competing replacements.
    - The failing request gets 500 `ENGINE_ERROR`. It is not retried automatically, because a deterministic crash would repeat.
    - The lifespan shuts the executor down on exit.
  - A non-blocking process-local guard allows one generation at a time. A second request gets 429 `GENERATION_IN_PROGRESS`. The guard is released in `finally`, on success, error and cancellation.
  - Requests are synchronous, about the solver time limit plus overhead. There is no queue infrastructure.
  - CP-SAT uses `num_workers = min(8, cpu_count)`.
- **Time:** one helper, `now_israel()`, based on `zoneinfo("Asia/Jerusalem")`, decides the current month and which shifts have started. The container clock is UTC.

## 3. Data model (PostgreSQL)
| Table | Key columns | Constraints / indexes |
|---|---|---|
| `users` | id, username, display_name, password_hash, app_role (PLANNER, MANAGER) | username UNIQUE |
| `workers` | id, national_id text, full_name, role, status (ACTIVE, INACTIVE), row_version, timestamps | national_id UNIQUE, CHECK `^[0-9]{9}$` (checksum enforced in app); index (status, role) |
| `contract_versions` | id, worker_id FK RESTRICT, version_no, effective_month date, hourly_rate_ils numeric(10,2), min_hours, max_hours, availability jsonb (sorted `["MON:A",…]`), created_at, created_by, source (UI/CSV), import_id | UNIQUE(worker_id, version_no); CHECK day=1, 0≤min≤max≤744, rate>0; index (worker_id, effective_month DESC, version_no DESC); trigger rejects UPDATE/DELETE |
| `csv_imports` | id, created_by, created_at, status (PENDING, CONFIRMED), preview jsonb (rows, classifications, base fingerprints), result jsonb, confirmed_at/by | Expiry is not enforced; confirmation is conditional on status |
| `rosters` | id, month date, status (DRAFT, APPROVED), forbid_adjacent_shifts bool DEFAULT false, row_version, generation_meta jsonb, updated_at/by | month UNIQUE, CHECK day=1 |
| `roster_assignments` | id, roster_id FK CASCADE, worker_id FK RESTRICT, date, shift, role (the slot role, snapshotted) | UNIQUE(roster_id, worker_id, date, shift); index (roster_id, date, shift); index (worker_id) |
| `roster_approvals` | id, roster_id, roster_version, approved_by, approved_at, acknowledged_warnings jsonb, reason, revoked_at, revoked_by, revoke_cause (EDIT, REGENERATE, CONTRACT_CHANGE, WORKER_CHANGE), revoke_ref | index (roster_id, approved_at DESC) |
| `worker_field_history` | id, worker_id FK RESTRICT, field (STATUS, ROLE), old_value, new_value, effective_at timestamptz, changed_by | index (worker_id, field, effective_at DESC); insert-only, no UPDATE/DELETE (trigger, as `contract_versions`) |

**Contract resolution** for month M: `effective_month ≤ M`, ordered by `effective_month DESC, version_no DESC`, first row. A future version can never resolve for an earlier month. There is no current-contract pointer, and the UI's "current contract" means resolved for the current Israel month.

**Violations, warnings and costs** are never stored. `rosters.evaluation` computes violations and warnings on read with the engine's `validate_roster` / `roster_metrics` (§4.2) against the current data. `rosters.costs` computes estimated costs on read (§6). Workers without an applicable contract become violation `NO_CONTRACT_FOR_MONTH` in the application layer.

**Worker status/role history (D9, resolved as (b)):** every PATCH that changes `status` or `role` inserts one `worker_field_history` row with `effective_at = now_israel()`, in the same transaction as the worker update. This is in addition to the worker row's current value, which is what the engine and generation always use for free (upcoming) shifts.
- `resolve_worker_state(worker_id, at: datetime) -> {status, role}`: the current worker row, with each field replaced by the `old_value` of the oldest history row for that field with `effective_at > at`, if one exists (that is, undo every change that happened after `at`). With no such row, the current value already holds at `at`.
- **Used only for locked (already-started) assignments.** `rosters.evaluation` checks each locked assignment's `INACTIVE_WORKER` / `WRONG_ROLE` against `resolve_worker_state(worker_id, shift_start(date, shift))`, not against the worker's current row.
  - A worker deactivated or given a new role after a shift started never turns that shift into a violation.
  - A worker who was already inactive or in a different role *before* the shift started still shows the violation, unchanged from today's behaviour.
- **Free (upcoming) shifts are unaffected:** their `INACTIVE_WORKER` / `WRONG_ROLE` checks (in the engine, in generation, and in P10 edits) always use the current worker row, since a future assignment must reflect current truth.
- The engine itself is not changed: it only ever sees the current worker row (via `WorkerInput`) and validates fixed assignments against it as before. The history-based override happens one layer up, in `rosters.evaluation`, which replaces the engine's `INACTIVE_WORKER`/`WRONG_ROLE` entries for locked-assignment keys with the historically resolved result before returning `preexisting_violations` to the API. Every other violation code from the engine passes through unchanged.
- History is read-only and small (one row per status/role change), so this adds one indexed lookup per locked assignment on read, not a new write path elsewhere.

**Concurrency:**
- Every write that touches scheduling data first takes one transaction-scoped Postgres advisory lock, `pg_advisory_xact_lock(SCHED)`. That covers worker edits, contract/import apply, roster save, edits and approval.
- Then optimistic checks run: `expected_version` against `row_version`, and fingerprint equality. A mismatch returns 409.
- Writes are serialized, which is fine for a local demo; reads and solving are unaffected.

## 4. Scheduling engine (`backend/app/scheduling/`)
The engine is pure Python on CP-SAT. It runs one weighted solve whose optimum is lexicographic (coverage first, then minimum hours). It reports solver statuses honestly and runs every returned roster through an independent validator. It has no database or web-framework dependencies. The application (`rosters/problem_builder`) resolves contracts and builds its input.

### 4.1 Domain
- **Shifts:** A 00:00–08:00, B 08:00–16:00, C 16:00–00:00. A shift belongs to its start date and counts as 8 hours. Slots are ordered chronologically by `(date, shift)`.
- **Roles:** GENERAL_GUARD, SCREENER, SUPERVISOR.
- **Demand:** a mapping `(shift, role) → headcount`, identical every day.
  - The default lives in one configurable constant in code, `DEFAULT_DEMAND`: 2 GENERAL_GUARD, 2 SCREENER, 1 SUPERVISOR per shift. That is 15 slots a day, or 465 in a 31-day month.
  - It is always passed into the engine; the engine never reads configuration itself.
- **Missing demand entries count as zero.** An omitted `(shift, role)` pair means demand 0. Unknown keys, negative values, and non-integer values are rejected.
  - Input validation normalizes the mapping once into a dense table, `demand_of(shift, role)`.
  - The model, validator, and diagnostics all read that table, so the three can never disagree.
- **Slot:** `(date, shift, role)` with `demand_of(shift, role) > 0`.
- **Uncovered worker slot:** one missing worker in one slot.
- **Daily limit:** at most 2 shifts per worker per calendar day.
- **Adjacent-shift rule (optional, off by default):**
  - The brief's only hard scheduling rule is the daily limit. `Problem.forbid_adjacent_shifts` (default `false`) optionally adds one more.
  - When it is on, A→B and B→C on the same day, and C on day d → A on day d+1, are back to back and forbidden. A+C on the same day stays allowed.
  - When it is off, there are no adjacency constraints and no `ADJACENT_SHIFTS` violations between shifts of the month itself.
  - When it is on, the rule applies to generation, manual edits, suggestions and the validator.
  - **Month boundaries:**
    - The engine always enforces pairs that involve a passed neighbor assignment, whatever the flag says.
    - The application decides which boundaries apply: a boundary pair counts if either of the two months' rosters has the rule on. It passes neighbor assignments only for those boundaries.
  - The application stores the setting per roster (§3, §6).
  - It is an optional product setting, not a claim of labour-law compliance.
- **Locked and free shifts:**
  - `free_from` is a `(date, shift)` position in the month. Shifts before it are locked; shifts at or after it are free.
  - The application sets `free_from` to the first shift whose start time is after `now_israel()`. A shift that has started is locked.
  - For a future month, `free_from` is `(1st, A)`. A fully locked month uses `(last day + 1, A)`.
  - Stored assignments in locked shifts are passed in as `fixed_assignments` and returned unchanged. The solver assigns free shifts only.
- **Neighbor-month assignments:**
  - These are the stored assignments on the previous month's last day and the next month's first day, if those rosters exist.
  - They are read-only and used only by the adjacency rule, when it applies: a C shift on the previous month's last day blocks A on the 1st, and an A shift on the next month's 1st blocks C on the last day.
  - The list is empty when no boundary applies.
  - They are never returned, counted toward hours or coverage, or modified.

### 4.2 Interface
```python
@dataclass(frozen=True)
class WorkerInput:  # contract already resolved for the month by the caller
    id: str
    role: Role
    active: bool
    availability: frozenset[tuple[Weekday, Shift]]
    min_hours: int
    max_hours: int

@dataclass(frozen=True)
class Assignment:
    worker_id: str
    date: date
    shift: Shift
    role: Role  # slot role, snapshotted; the validator checks it against the worker's role

@dataclass(frozen=True)
class Violation:
    code: ViolationCode
    key: tuple                # stable scope, see §4.5
    magnitude: int            # ≥ 1, see §4.5
    assignments: tuple[Assignment, ...]

@dataclass(frozen=True)
class Problem:
    year: int
    month: int
    demand: Mapping[tuple[Shift, Role], int]
    workers: Sequence[WorkerInput]
    free_from: tuple[date, Shift]                        # (1st, A) ≤ free_from ≤ (last day + 1, A)
    fixed_assignments: Sequence[Assignment] = ()         # all before free_from
    neighbor_assignments: Sequence[Assignment] = ()      # previous month's last day and next month's first day, only for boundaries where the rule applies
    forbid_adjacent_shifts: bool = False                 # optional rule (§4.1); off = the brief's rules only

@dataclass(frozen=True)
class SolverConfig:
    time_limit_s: float = 10.0  # CP-SAT search time for the single solve
    num_workers: int = 8        # the application passes min(8, cpu_count)
    random_seed: int = 0

def solve(problem, config) -> ScheduleResult
def validate_problem(problem) -> list[InputError]
def validate_roster(problem, assignments) -> list[Violation]   # adjacency within the month only if the flag is on; always against neighbor_assignments
def roster_metrics(problem, assignments) -> Metrics            # coverage gaps and hour shortfalls, recomputed from the roster
def worsened(before: list[Violation], after: list[Violation]) -> list[Violation]  # §4.5; shared with P10
def diagnose(problem) -> Diagnostics
```
These types, the result types (§4.6) and the API schemas (§6) are the shared contract. They are defined and frozen in T0, before work splits (§8, §9).

**Input validation:** `validate_problem` rejects the problem if any of these fail:
- worker ids are unique
- `0 ≤ min_hours ≤ max_hours`
- demand uses only known keys and has integer values ≥ 0
- the month is valid
- `free_from` is within its range
- every fixed assignment is inside the month and before `free_from`, and no `(worker_id, date, shift)` appears twice
- every neighbor assignment is on the previous month's last day or the next month's first day
- `W · (free slots) + S_max < 2^53` (§4.4), so objective values and bounds stay exact in a double. Realistic data is about 3·10^6.

A fixed assignment that references an inactive or unknown worker, or that breaks the current contract, is **not** an input error. §4.3 handles it.

**Test seam:** CP-SAT is called through one thin function, `_run_cp_sat(model, config) -> RawSolve(status, values, objective, bound, wall_time)`. Tests can mock it to force any status.

### 4.3 Hard constraints and the fixed-assignment policy
**Policy:**
- Fixed assignments are history. They may break the current data, for example after a retroactive contract change.
- Their existing violations stay visible and are never repaired.
- New assignments must not introduce any new hard violation or make an existing one worse.
- The model enforces this below. The independent validation gate enforces it again (§4.5).

Treating fixed assignments as constants is not enough on its own. Example: fixed assignments total 80 hours and a retroactive change lowers `max_hours` to 64. A naive `80 + new_hours ≤ 64` is infeasible. So every constraint below uses the capacity that remains after the fixed assignments, floored at 0.

Notation (fixed counts come from `fixed_assignments` only):
- `max_shifts_w = floor(max_hours_w / 8)`
- `fixed_hours_w = 8 · (fixed shifts of w)`
- `fixed_day(w,d)` = fixed shifts of w on day d
- `fixed_slot(d,s,r)` = fixed assignments in slot `(d,s,r)`

The constraints:
- **Inactive workers are excluded completely.** They get no variables, no `short[w]` term, no hour-shortfall entry and no capacity diagnostic. The validator reports any assignment to an inactive worker, fixed or not, as a violation.
- **Assignment variables:** `x[w,d,s]` exists only if all of these hold:
  - `(d,s)` is free
  - w is active and available on that weekday and shift
  - `demand_of(s, role_w) > 0`
  - no fixed assignment of w is at `(d,s)`
  - no neighbor assignment of w is adjacent to `(d,s)`
  - if `forbid_adjacent_shifts` is on: no fixed assignment of w is adjacent to `(d,s)`

  Eligibility is checked against the current data for new assignments only. Fixed assignments are never re-checked.
- **Monthly limit:** `new_hours_w ≤ max(0, max_hours_w − fixed_hours_w)`, which is `Σ x[w,·,·] ≤ floor(max(0, max_hours_w − fixed_hours_w) / 8)`.
- **Daily limit:** `Σ_s x[w,d,s] ≤ max(0, 2 − fixed_day(w,d))`. A day can hold both fixed and free shifts; for example, at 10:00 shifts A and B are locked and C is free.
- **Adjacency (only if `forbid_adjacent_shifts` is on, except neighbor pairs, which are always handled above):**
  - For free pairs: `x[w,d,A] + x[w,d,B] ≤ 1`, `x[w,d,B] + x[w,d,C] ≤ 1`, and `x[w,d,C] + x[w,d+1,A] ≤ 1`.
  - Pairs that involve a fixed or neighbor shift are handled by not creating the variable (above).
  - A fixed pair that is already adjacent stays as it is and is reported.
- **No overstaffing:** `Σ_{w∈r} x[w,d,s] ≤ max(0, demand_of(s,r) − fixed_slot(d,s,r))`. Free slots have no fixed assignments today, but the rule is written generally.
- **Duplicates:** there is at most one variable per `(w,d,s)` and none where a fixed assignment exists.
- **Invariant: zero new assignments is always feasible.** Set every `x` to 0:
  - **Monthly, daily and overstaffing:** the left side is 0, and every right side has the form `max(0, …)`, which is ≥ 0.
  - **Adjacency:** `0 + 0 ≤ 1`.
  - **`uncovered[d,s,r]`** equals the remaining demand of its slot, which lies inside its domain `[0, max(0, demand_of(s,r) − fixed_slot(d,s,r))]`.
  - **`short[w]`** can take `max(0, min_hours_w − fixed_hours_w)`, which lies inside its domain `[0, min_hours_w]` because `fixed_hours_w ≥ 0`.
  - **Coverage and minimum hours are soft.** They are slack terms in the objective, never hard constraints.
  - **Fixed assignments are never constraints.** They only lower right-hand sides (floored at 0) or stop variables from being created. So an existing fixed violation can never produce an unsatisfiable row; §4.5 reports it instead.
  - Implementation note: the model builder must declare exactly these domains. A test checks the invariant (§4.9).
- **Unexpected INFEASIBLE:**
  - It is handled gracefully, never as a crash. The engine returns `EngineError(solver_status=INFEASIBLE)` with diagnostics and timings.
  - The application logs it with a problem summary (month, worker count, `free_from`, fixed count) and persists nothing. The API returns 500 `ENGINE_ERROR`, and the existing roster is untouched.
  - The UI shows the error panel with "nothing was changed".
- **Not enforced, by design:** any other rest rule. With the setting off (the default), only the daily limit applies, as the brief states. With it on, C followed by the next day's B (an 8-hour gap) is still allowed.

### 4.4 Objective (one weighted solve)
**Terms** (active workers in the input only; free slots only):
- `uncovered[d,s,r] = max(0, demand_of(s,r) − fixed_slot(d,s,r)) − Σ_{w∈r} x[w,d,s]`, which is ≥ 0 by the overstaffing rule
- `short[w] ≥ min_hours_w − 8·Σ x[w] − fixed_hours_w`, with `0 ≤ short[w] ≤ min_hours_w`

**Weight:** `S_max = Σ min_hours_w` over active workers, and `W = S_max + 1`.

**Minimize** `W · Σ uncovered + Σ short`.

**Locked and free shortages are counted separately.**
- Locked slots (before `free_from`) and free slots (at or after `free_from`) are disjoint and together cover the whole month.
- **Locked slots:** the model has no variables and no `uncovered` terms for them. Their gaps are the same in every solution. They are computed once by `roster_metrics` over locked slots only, as `locked_uncovered`.
- **Free slots:** the objective's `U` is `U_free`, the uncovered total over free slots only. Fixed hours appear only inside `short[w]`, never in `uncovered`.
- Every gap is counted exactly once: `total_uncovered = locked_uncovered + U_free`.

**Why the priority holds:**
- The cap `short[w] ≤ min_hours_w` makes `0 ≤ Σ short ≤ S_max < W` hold in every feasible solution, not only at the optimum.
- The cap never cuts off the true value `max(0, min − hours)`.
- Suppose roster P has fewer uncovered slots than roster Q (`U_P ≤ U_Q − 1`). Then `obj(P) ≤ W(U_Q − 1) + S_max < W·U_Q ≤ obj(Q)`.
- So an optimal solution minimizes coverage gaps first, and then hour shortfall among the rosters with that coverage. At OPTIMAL, the roster is lexicographically optimal.

**Coverage lower bound from the solver bound:**
- Every feasible solution satisfies `W·U + S ≥ objective_bound` and `S ≤ S_max`. Therefore `U ≥ (objective_bound − S_max) / W`.
- **Rounding, conservatively:**
  - `B = ceil(objective_bound − 1e-6)`. The objective is an integer; the epsilon stops float noise such as `12.0000001` from rounding up to 13 and overstating the bound.
  - Then `LB_free = max(0, ceil_div(B − S_max, W))`, computed in integers.
- **Reported value:** `coverage.lower_bound = locked_uncovered + max(LB_free, LB_diag_free)`.
  - Both terms inside `max` bound `U_free` only.
  - `LB_free` comes from an objective that contains free slots only.
  - `LB_diag_free` is the proven diagnostic bound of §4.7, which is computed over free slots only.
  - Neither term includes locked shortages, so nothing is counted twice. The maximum of two valid lower bounds on the same quantity is itself a valid lower bound.
- **Exact when tight:** if `objective_bound = W·U* + S*`, then `(S_max − S*) / W < 1`, so the formula returns exactly U*. At OPTIMAL it equals `total_uncovered`.

**Timeout limitations** (documented in the README):
- At FEASIBLE there is no separate bound on hour shortfall. Minimum hours is reported as FEASIBLE with no bound.
- The coverage lower bound is only as strong as CP-SAT's objective bound. A loose bound can give 0 even when gaps are unavoidable. The diagnostic bound (§4.7) is the fallback.
- With a large W, the raw objective gap looks big. The UI shows only derived values.

**Time limit:** `time_limit_s` (default 10 s, configurable) is CP-SAT search time. It is not an end-to-end response deadline.
- Measured and reported separately: input validation, diagnostics, model build, search, roster validation, and total elapsed time.
- Benchmarks (§4.8) set the default.

### 4.5 Violations, validation gate and status handling
**Violation keys and magnitudes** (stable across calls):

| Code | Key scope | Magnitude |
|---|---|---|
| INACTIVE_WORKER | worker, date, shift | 1 |
| UNKNOWN_WORKER | worker, date, shift | 1 |
| WRONG_ROLE | worker, date, shift | 1 |
| UNAVAILABLE | worker, date, shift | 1 |
| OUT_OF_MONTH | worker, date, shift | 1 |
| DUPLICATE_ASSIGNMENT | worker, date, shift | copies − 1 |
| DAILY_LIMIT | worker, date | shifts − 2 |
| ADJACENT_SHIFTS | worker, (date, shift) of the earlier shift in the pair | 1 |
| MAX_HOURS | worker | assigned hours − max_hours |
| OVERSTAFFED | date, shift, role | assigned − demand |

`ADJACENT_SHIFTS` is reported for pairs inside the month only when `forbid_adjacent_shifts` is on. Pairs formed with a passed neighbor assignment are always reported. The key names the earlier shift, which may be in the neighbor month.

**`worsened(before, after)`** returns every violation in `after` whose key is missing from `before`, or whose magnitude is larger than before. Comparing keys alone is not enough. Example: a worker is already 16 h over `MAX_HOURS`. Adding a shift keeps the same key but raises the magnitude to 24, and that must be rejected.

**Validation gate:** every candidate roster (fixed + new) goes through the gate.
- `V_fixed = validate_roster(problem, fixed)` and `V_full = validate_roster(problem, full)`.
- The roster is accepted only if `worsened(V_fixed, V_full)` is empty.
- All of `V_full` is returned as `preexisting_violations`, so existing violations stay visible.
- Reported metrics always come from `roster_metrics` on the returned roster, never from solver values.

**Status handling:**

| CP-SAT result | Behaviour |
|---|---|
| OPTIMAL | `Solved`. Coverage OPTIMAL, minimum hours OPTIMAL, `lexicographically_optimal = true` |
| FEASIBLE | `Solved`. Coverage lower bound per §4.4. Coverage is OPTIMAL if `lower_bound = total_uncovered`, otherwise FEASIBLE. Minimum hours FEASIBLE with no bound. `lexicographically_optimal = false` |
| UNKNOWN with no solution | `NoSolutionWithinLimit` carrying the coverage lower bound. This is not a claim of infeasibility. The caller must not replace any existing roster |
| MODEL_INVALID, INFEASIBLE, or gate failure | `EngineError`. INFEASIBLE here is unexpected (§4.3 invariant) |

### 4.6 Result type (discriminated union)
```python
ScheduleResult = Solved | NoSolutionWithinLimit | InvalidInput | EngineError

Solved:
  assignments: list[Assignment]  # fixed ones included, unchanged
  coverage_gaps: list[{date, shift, role, required, assigned, missing, proven_missing, locked}]
  hour_shortfalls: list[{worker_id, min_hours, assigned_hours, missing_hours}]  # active workers only
  coverage:  {status: OPTIMAL|FEASIBLE, total_uncovered, locked_uncovered, lower_bound}
  min_hours: {status: OPTIMAL|FEASIBLE, total_shortfall}
  lexicographically_optimal: bool
  preexisting_violations: list[Violation]
  objective: {weight, s_max, value, bound}  # raw, for benchmarks and debugging only
  free_from, diagnostics, timings, warnings

NoSolutionWithinLimit:
  coverage_lower_bound: int  # locked_uncovered + max(solver-derived, diagnostic); no roster metrics
  diagnostics, timings

InvalidInput: errors
EngineError: solver_status, message, diagnostics|None, timings
```
- Outcomes without a roster carry no roster metrics. An empty roster is never passed off as generated.
- **Proof of impossibility:** full coverage of the free shifts is proven impossible only if `lower_bound − locked_uncovered ≥ 1`. Locked gaps have already happened and are reported separately.
- **API mapping:**

  | Outcome | HTTP |
  |---|---|
  | `Solved` | 200 |
  | `NoSolutionWithinLimit` | 200, with an outcome type and no roster |
  | `InvalidInput` | 422 |
  | `EngineError` (including an unexpected INFEASIBLE and a crashed pool) | 500 `ENGINE_ERROR` |

  Nothing is persisted in any of these cases.

### 4.7 Diagnostics (`diagnose`, pure and cheap, active workers, free shifts only)
**Definitions (free slots only):**
- `remaining_demand(d,s,r) = max(0, demand_of(s,r) − fixed_slot(d,s,r))` for a free `(d,s)`.
- `remaining_demand_r = Σ_{free (d,s)} remaining_demand(d,s,r)`.
- `remaining_max_shifts_w = floor(max(0, max_hours_w − fixed_hours_w) / 8)`, the right side of the monthly limit in §4.3.

**Proven facts.** Each one is a lower bound that holds in every feasible solution of §4.3. None is a heuristic.
- **Slot deficit:** `slot_deficit(d,s,r) = max(0, remaining_demand(d,s,r) − eligible(d,s,r))`.
  - `eligible` counts the workers of role r that satisfy all of these:
    - `x[w,d,s]` exists (§4.3)
    - `remaining_max_shifts_w ≥ 1`
    - `max(0, 2 − fixed_day(w,d)) ≥ 1`
  - *Proof:* only those workers can take the slot, each at most once (x is boolean), so at most `eligible` workers fill it.
- **Worker capacity:** `cap_w = min(remaining_max_shifts_w, Σ_{free d} day_cap(w,d))`.
  - `day_cap(w,d) = min(max(0, 2 − fixed_day(w,d)), k)`, where k is:
    - with the rule on: the size of the largest non-adjacent subset of the free shifts on d where `x[w,d,·]` exists. The subset has size 2 only for {A, C}.
    - with the rule off: the number of free shifts on d where `x[w,d,·]` exists.
  - *Proof:* the monthly limit, the daily limit and, with the rule on, same-day adjacency each cap w's new shifts. Ignoring cross-day adjacency only drops a constraint, so `cap_w` stays an upper bound on the new shifts of w.
- **Role deficit:** `role_deficit_r = max(0, remaining_demand_r − Σ_{w∈r} cap_w)`.
  - *Proof:* a worker only fills slots of its own role, one unit each, so role r gets at most `Σ cap_w` of its free slots filled.
- **Role lower bound:** `LB_r = max(Σ_{free slots of r} slot_deficit, role_deficit_r)`.
  - *Proof:* `U_free,r` is the sum of per-slot uncovered counts, so the per-slot bounds add up. The maximum of two valid bounds is valid.
- **Total:** `LB_diag_free = Σ_r LB_r`. Roles partition the free slots, so the sum is valid.
  - It excludes locked slots by construction, so it never includes `locked_uncovered` (§4.4).
- **Worker shortfall:** `max(0, min_hours_w − fixed_hours_w − 8·cap_w)` is a lower bound on `short[w]`, because `8·cap_w` bounds the new hours.
- **From the solver:** the bound described in §4.4.

**Suspected causes:**
- In each gap, `proven_missing` is the slot-deficit part. Any gap beyond it is labelled `SUSPECTED`, with a hint such as "eligible workers at max hours, at the daily limit, or blocked by an adjacent shift".
- `SUSPECTED` labels and hints are UI explanations only. They never feed into `LB_diag_free` or any reported bound.
- A proven minimum gap count does not mean these particular slots must stay unfilled in every solution, so gap locations are never presented as proven.
- Proving that a specific slot can never be filled would need a separate solve per slot; that is out of scope.

### 4.8 Benchmarks (`backend/bench/`)
Benchmarks run on the actual model: weighted objective, fixed assignments, neighbor assignments, and the adjacency rule both off (the default) and on. They measure behaviour; they do not require proven optimality at every size.

**Time budget (documented in the README):**
- Every run uses the default `time_limit_s = 10`.
- The scale runs are also repeated at `time_limit_s = 60`.
- `num_workers = 8` and `random_seed = 0`.
- The README records the hardware.

**Small fixtures.** A seeded generator builds 30- and 31-day months with `DEFAULT_DEMAND`:
- **comfortable:** about 40 workers
- **tight:** capacity ≈ demand
- **short:** too few supervisors
- **fragmented:** sparse availability
- **min-hours pressure:** high minimums
- **with inactive workers**
- **mid-month:** `free_from` on day 15 at shift B, with fixed assignments from an earlier solve
- **retroactive conflict:** fixed assignments that exceed the reduced `max_hours` or violate the current availability
- **neighbor months:** C shifts on the previous month's last day and A shifts on the next month's first day

**Scale fixtures:**
- 200, 500 and 1,000 active workers, in a 31-day month.
- Demand is `k × DEFAULT_DEMAND`, with k chosen so that capacity/demand matches the comfortable fixture. That represents the same staffing ratio across more sites.
- Each size also runs at fixed `DEFAULT_DEMAND`, to show the cost of a large pool of workers against small demand.
- One mid-month variant per size.
- The input validation guard keeps `W · slots + S_max < 2^53`; a 1,000-worker run is far below it.

**Recorded per run:**
- **Runtime:** input validation, model build, search and total elapsed time, plus variable and constraint counts.
- **Solver status:** OPTIMAL, FEASIBLE or UNKNOWN.
- **Solution quality:** `total_uncovered`, `total_shortfall`, and `lexicographically_optimal`.
- **Bounds:** the raw objective and objective bound, the derived coverage lower bound, the diagnostic bound, and the coverage gap `total_uncovered − lower_bound`.

The README reports the results as measured, with the time budget and hardware.
- Adopting the weighted model does not depend on runtime.
- If some instances hit the time limit, report that. Then either adjust the default limit or document the gap.
- Do not assume a two-phase model would have been faster.

### 4.9 Engine tests (pytest, deterministic)
Tests assert totals and invariants, never exact assignments (except where fixed assignments must come back unchanged).

**Input and demand**
- Rejected inputs:
  - duplicate ids
  - `min > max`
  - negative or non-integer demand
  - unknown demand key
  - `free_from` out of range
  - fixed assignment at or after `free_from` or outside the month
  - duplicate fixed assignment
  - neighbor assignment on a wrong date
  - weight overflow guard
- Omitted demand entry:
  - no assignments go to that slot
  - no gap is reported for it
  - the validator flags a hand-made assignment there as overstaffing
  - diagnostics ignore it

**Validator and `worsened`**
- One test per violation code in §4.5, plus a valid roster. Adjacency (rule on) covers A→B, B→C, C→next-day A, and C on the previous month's last day → A on the 1st (via neighbor assignments).
- Rule off: A+B, B+C and C→next-day A inside the month produce no `ADJACENT_SHIFTS`, but a pair with a passed neighbor assignment is still reported. Three shifts in one day are still `DAILY_LIMIT`.
- The key and magnitude for each code match §4.5.
- `worsened`:
  - a new key is reported
  - the same key with a higher magnitude is reported
  - the same key with the same or lower magnitude is not reported
- Metrics:
  - recomputed gaps and shortfalls are correct
  - inactive workers are absent from shortfalls

**Solver fixtures (hand-computed optima)**
- fully coverable: 0 gaps, lexicographically optimal
- one supervisor for a 3-shift demand, in both modes: at most 2 shifts a day (any 2 with the rule off, only A+C with it on). The gap equals demand minus capacity, and it is proven
- adjacency, rule on: an instance that could only be fully covered with back-to-back shifts leaves a gap; no adjacent pair appears in the output
- same instance, rule off: fully covered, using back-to-back shifts
- weight sufficiency: covering one extra slot costs the largest possible shortfall increase, and coverage still wins. The fixture is built so that a weight of 1 would pick the other roster; the hand-computed values are in the test docstring
- among coverage-optimal rosters, the one with minimum shortfall is returned
- greedy trap: most-constrained-first greedy leaves a gap, but CP-SAT covers everything
- an inactive worker with a high minimum: no assignments, no shortfall, not counted in capacity
- tiny brute-force check: `free_from` leaves 2 free shifts and 2 workers. Every roster is enumerated, and the solver's `(uncovered, shortfall)` equals the lexicographic minimum

**Fixed assignments and existing violations**
- **Retroactive cap reduction:**
  - fixed 80 h, `max_hours` lowered to 64: `Solved`, no new assignments for that worker, `MAX_HOURS` magnitude stays 16 and is listed, and the gate accepts
  - fixed 56 h with a 64 h maximum: at most 1 new shift
- **Adjacency to a fixed shift (rule on):**
  - fixed B on day d (started, C free): the worker is not assigned C on d
  - fixed C on day d−1: the worker is not assigned A on d
  - fixed A on day d: C on d is allowed
- **Fixed shift with the rule off:** fixed B on day d allows C on d, within the daily limit.
- **Neighbor months:** C on the previous month's last day blocks A on the 1st; A on the next month's 1st blocks C on the last day. This holds whenever neighbor assignments are passed, including with the rule off.
- **Mid-day cutoff:** with `free_from = (d, C)`, the A and B assignments on d are unchanged and the daily limit counts them.
- **Other existing violations:** a fixed assignment for an inactive worker, a fixed unavailable shift, or a fixed adjacent pair is returned unchanged, stays visible with the same magnitude, and does not make the model infeasible.
- **Fully locked month:** the fixed assignments are returned as they are, and the status is OPTIMAL.
- **Gate:** an injected solution that adds a shift to a worker already over the cap (magnitude 16 → 24) is rejected, even though the key is the same.

**Coverage bound arithmetic (pure function)**
- a tight bound returns exactly U*
- a bound with float noise (for example `k + 1e-9`) does not overstate
- a bound below `S_max` gives 0
- `locked_uncovered` is added
- the result is the maximum with the diagnostic bound

**Locked/free separation and feasibility invariant**
- Mid-month fixture with gaps in both locked and free slots:
  - `locked_uncovered` equals the gaps in locked slots only
  - `LB_free ≤ U_free` and `LB_diag_free ≤ U_free`
  - `lower_bound ≤ total_uncovered`
  - `total_uncovered = locked_uncovered + U_free`
  - no locked gap is counted in either inner bound
- A fixture whose locked slots are all uncovered and whose free slots are fully coverable: `lower_bound = locked_uncovered`.
- Zero-roster invariant: on the retroactive-conflict fixture (cap below the fixed hours, a fixed adjacent pair, a fixed inactive worker), add `x = 0` for every variable and solve. The result must be OPTIMAL. This guards the variable domains of §4.3.

**Status paths (mocked `_run_cp_sat`)**
- OPTIMAL: both statuses OPTIMAL, `lexicographically_optimal = true`, lower bound equals `total_uncovered`
- FEASIBLE: coverage FEASIBLE with the derived bound, minimum hours FEASIBLE with no bound, `lexicographically_optimal = false`
- FEASIBLE with a lower bound equal to `total_uncovered`: coverage OPTIMAL, `lexicographically_optimal = false`
- UNKNOWN with no solution: `NoSolutionWithinLimit` with a bound and no metrics
- MODEL_INVALID or INFEASIBLE: `EngineError`
- an injected invalid solution: rejected by the gate

**Real tiny time limit (smoke test)**
- On a simple instance, any of these outcomes is acceptable, including OPTIMAL:
  - `Solved`, with any status
  - `NoSolutionWithinLimit`
- It must never claim infeasibility, and every returned roster passes the gate.

**Diagnostics**
- slot and role deficits are correct
- `day_cap` respects fixed shifts in both modes, and adjacency only with the rule on
- inactive workers are excluded
- gaps beyond `proven_missing` are marked `SUSPECTED`
- `LB_diag_free ≤ U_free` on every solver fixture, including the mid-month ones
- worker-shortfall lower bound ≤ the returned `short[w]` on every solver fixture

**Independence**
- The engine never imports sqlalchemy, fastapi, or any `app.*` module outside `scheduling`. Checked by an import-linter contract or a test.

**Deferred (P1):** Hypothesis property-based tests on random small instances.

## 5. Application policies (accepted, D2, §12)
- **P1 Same-month revisions:** allowed. A new version with the same `effective_month` supersedes the earlier one because its `version_no` is higher. Both are kept.
- **P2 Past effective months:** allowed. The preview labels them "retroactive" and lists the affected rosters.
  - **Locked-violation warning (D8):** before a retroactive contract change is confirmed, through the UI or a CSV import, the preview states the consequences if the change creates new hard violations in shifts that have already started.
    - Example: "Approval of 2026-09 will be revoked. 3 violations fall in shifts that have already started and cannot be fixed by editing assignments. The roster will stay unapproved unless the contract data is corrected."
    - The list shows worker, date, shift and code.
    - The warning comes from the change-set's existing revalidation, which splits new hard violations into locked and editable. It is only this warning, not a general preview feature.
- **P3 Historical rosters and locked shifts:**
  - Rosters for months before the current Israel month are read-only history. They are not revalidated, edited, regenerated or approved, and are shown without violation evaluation.
  - In the current month, shifts that have already started (§4.1) are immutable.
    - Regeneration keeps them and reschedules only future shifts.
    - Save and manual edits (add, remove, move) that touch a started shift return 422 `LOCKED_SHIFT`.
    - History is never edited.
- **P4 Active worker without an applicable contract:** excluded from engine input and suggestions. The generation preview lists them ("no contract for 2026-11"). Existing assignments show `NO_CONTRACT_FOR_MONTH`.
- **P5 Identical data:** a contract whose fields (rate, min, max, availability) equal the version resolved at the row's effective month creates no version. Worker fields unchanged means no update.
- **P6 Worker deletion:** hard delete only if the worker has no contract versions and no assignments. Otherwise the API returns 409 `WORKER_IN_USE`, and the UI offers "deactivate" instead. History is preserved.
- **P7 Status and role changes** (not month-versioned):
  - Applying one revalidates the affected rosters (current and future months that contain the worker). Approved rosters that gain hard violations return to draft and their approval is revoked (`WORKER_CHANGE`), the same as for contract changes.
  - Assignments keep their snapshotted slot role, so a role change shows up as a `WRONG_ROLE` violation on *upcoming* shifts. Nothing moves silently.
  - **Locked (already-started) shifts are evaluated against the worker's status/role as of when the shift started (D9(b)), not against the value after this change.** Every status/role change is recorded in `worker_field_history` for this (§3). A change made mid-month therefore cannot turn an already-worked shift into `INACTIVE_WORKER` or `WRONG_ROLE`; it only affects shifts that had not started yet when the change was applied.
  - The detailed impact preview before apply (the list of affected rosters) is deferred (P1). Until then the UI shows a simple confirmation.
- **P8 Duplicate national IDs in one file:** every row with that ID is INVALID (`DUPLICATE_IN_FILE`). Other rows are processed.
- **P9 Repeated confirmation:** the second confirm returns 409 `ALREADY_CONFIRMED` with the stored result. Nothing is applied twice.
- **P10 Incremental repair rule** (manual edits):
  - Uses the violation keys and magnitudes of §4.5 and the engine's `worsened(before, after)`. It is never simplified to counts.
  - An edit, including a move as remove+add, is accepted only if `worsened(before, after)` is empty.
    - Adjacency is checked only where the rule applies: inside the month if the roster has it on, and across a boundary if either month's roster has it on.
  - Edits that touch a started shift are rejected with `LOCKED_SHIFT` before this check (P3).
  - A removal from a free shift always passes. Coverage and hour warnings never block.
  - Generation and manual edits on a clean roster therefore enforce all hard constraints. Only contract/worker changes may introduce violations.
- **P11 Approving with warnings.** Soft shortages and hard violations are separate categories. The acknowledgement covers soft shortages only.
  - **Soft shortages (can be acknowledged):** coverage gaps, in both locked and upcoming shifts, and minimum-hour shortfalls. Nothing else is soft.
  - **Hard violations (can never be acknowledged):** every code in §4.5, plus `NO_CONTRACT_FOR_MONTH`.
    - Any hard violation blocks approval with 422 `HARD_VIOLATIONS` and the list, whatever `acknowledge_warnings` says.
    - There is no override parameter, flag or role that bypasses this.
  - With soft shortages present, a manager may approve only with `acknowledge_warnings=true`, a non-empty reason, and a `warnings_fingerprint` (a hash of the soft shortages the UI showed).
    - A fingerprint mismatch returns 409 `STALE_PREVIEW`, so the acknowledgement always matches the stored snapshot.
    - The snapshot (`acknowledged_warnings`) and the reason are stored with the approval.
  - With no soft shortages, approval needs no acknowledgement.
  - **Hard violations in started shifts (D8, resolved):**
    - Started shifts are immutable (P3), and a hard violation in one stays visible and blocks approval like any other.
    - If the contract data was wrong, it is corrected through the normal versioning policy (P1 same-month revision, or a new version with the right `effective_month`). History is preserved, and the roster revalidates.
    - If the violation is genuine, the roster stays unapproved. There is no bypass.
    - The consequence is announced before the change is confirmed (P2).
- **P12 Permissions:**
  - PLANNER: workers, contracts, CSV import/export, generation, drafts, edits. Editing an approved roster needs an explicit acknowledgement and returns it to draft.
  - MANAGER: everything a planner can do, plus approve.
  - The worker role SUPERVISOR is unrelated to app permissions.
- **P13 Export version:** one row per worker with the version effective for the chosen month (default: the current month), otherwise the next future version. **(D10, accepted)** Workers with no applicable contract are still exported, with the contract columns empty and `effective_month` empty; they are counted separately in the response as "no contract" rather than skipped, matching the brief's "full worker list". Rows with contract data carry the version's own `effective_month`, so re-importing an unmodified export gives all rows UNCHANGED. Importing a worker-only row (no contract columns filled) is valid and creates or updates the worker with no contract version.
- **P14 CSV format:**
  - Encoding: UTF-8 (a BOM is accepted on import and written on export, for Hebrew in Excel).
  - **Columns are matched by header name, in any order.**
    - A header row is required.
    - Headers are normalized: trimmed, lowercased, with spaces and hyphens turned into `_`.
    - Documented header aliases:

      | Column | Aliases |
      |---|---|
      | `national_id` | `id`, `israeli_id`, `id_number` |
      | `full_name` | `name` |
      | `hourly_rate_ils` | `hourly_rate`, `hourly_cost` |
      | `min_monthly_hours` | `min_hours` |
      | `max_monthly_hours` | `max_hours` |
      | `available_days` | `days` |
      | `available_shifts` | `shifts` |

    - Errors and warnings:
      - A missing required column returns 400 `MISSING_COLUMNS` with the list.
      - Two headers that normalize to the same name return 400 `DUPLICATE_COLUMN`.
      - Unknown columns are ignored and listed as a warning in the preview.
    - **Always required:** `national_id`, `full_name`, `role`.
    - **Contract columns** (`hourly_rate_ils`, `min_monthly_hours`, `max_monthly_hours`, and availability in one of the two forms below): required together as a group, unless every one of them is empty for that row, which makes it a worker-only row with no contract version (D10). A row with some contract columns filled and others empty is INVALID `INCOMPLETE_CONTRACT`.
    - **Optional, with defaults (D11, accepted):**
      - `status`: missing column or empty cell defaults to ACTIVE.
      - `effective_month` (YYYY-MM): missing column or empty cell defaults to the current Israel month (from `now_israel()`, frozen per import). The preview always shows the resolved value, not blank.
  - **Values.** Role and status are matched case-insensitively, with spaces, hyphens and underscores treated as equal.
    - GENERAL_GUARD ← `General Guard`, `general-guard`, `GENERAL_GUARD`, `Guard`
    - SCREENER ← `Screener`
    - SUPERVISOR ← `Supervisor`
    - ACTIVE / INACTIVE ← `Active`, `Inactive`
    - The README lists these aliases.
  - **Availability: exactly one form per row.**
    - **Per-day form:** `availability` = `MON:AB|TUE:ABC|FRI:C`. The worker is available only for the listed pairs.
    - **Brief form:** `available_days` plus `available_shifts`. The worker is available for **every listed shift on every listed day** (a cross product).
      - Days are `Sun`…`Sat` or full names, case-insensitive.
      - Shifts are `A`/`B`/`C` or `Morning`/`Day`/`Evening`. Letters may also be run together (`AB`).
      - Tokens are separated by `|` or `;`, or by `,` when the field is quoted.
      - Duplicate tokens are ignored.
    - **Invalid rows:**
      - both forms filled: INVALID `AMBIGUOUS_AVAILABILITY`
      - only days or only shifts: INVALID `INCOMPLETE_AVAILABILITY`
      - an empty result: INVALID `MISSING_AVAILABILITY`
      - an unknown token: INVALID, naming the token
    - Both forms normalize to the same set of (day, shift) pairs, so UNCHANGED/CHANGED classification does not depend on the form.
    - Export always writes the lossless per-day `availability` form.
  - **Identifiers are strings.**
    - `national_id` is never parsed as a number. It is trimmed, then must be exactly 9 digits and pass the checksum.
    - The brief defines no normalization, so shortened IDs are **not** padded. They are INVALID `ID_LENGTH`, with the message "must be exactly 9 digits (got 8); spreadsheets often drop leading zeros".
    - Scientific notation (`1.23E+08`) is INVALID `ID_FORMAT` with the same hint.
  - **Formula protection and round trip (applied to `full_name`, the only free-text field):**
    - **Source marker:** every exported file has an `export_format` column whose value is `icts-export-v1` in each row. Each row's source is decided by that column, never guessed from the name.
      - **External row** (column absent, or value empty): the name is taken **verbatim**. A leading apostrophe is never treated as an escape, so `'Neil` and `'=x` are stored exactly as written.
      - **Export row** (value `icts-export-v1`): the name is unescaped by the rule below.
      - Any other value: INVALID `UNKNOWN_EXPORT_FORMAT`.
    - **Escaping (export only):** trigger set `T = { = + - @ TAB CR ' }`. If a name starts with a character in T, export writes `'` followed by the name.
    - **Unescaping (export rows only):** if the name starts with `'` and its second character is in T, drop exactly that first `'`. Otherwise keep it verbatim.
    - **Round trip:**
      - Export escapes exactly the names that start with a character in T, and each escaped value is `'` plus a character in T, which import unescapes.
      - An unescaped name never starts with `'`, because `'` is in T, so import leaves it alone.
      - So `import(export(x)) = x` for every name, whichever source it originally came from.
      - The guarantee covers the file as exported. What happens if a spreadsheet re-saves it is checked by hand and documented in the README.
    - All other exported fields are validated (digits, enums, non-negative numbers) and cannot start with a trigger. Export asserts this.
  - **Limits:** 1 MB (1,048,576 bytes) per file and 5,000 data rows. The header and blank lines do not count.
    - **Bytes, enforced while reading:**
      - `POST /imports` accepts only a raw CSV body (`Content-Type: text/csv`). Any other content type returns 415.
      - The handler reads `request.stream()` in chunks and counts bytes. A `Content-Length` over the limit is rejected before reading, and a stream that goes past the limit is aborted at once, with 413 `FILE_TOO_LARGE`.
      - nginx `client_max_body_size 2m` is an outer backstop only.
    - **Rows, enforced during parsing:** `csv.reader` counts data rows as it iterates and stops at row 5,001 with 413 `TOO_MANY_ROWS`. Nothing is stored.
    - **Decoding:** UTF-8, with an optional BOM, strict. Invalid bytes return 400 `INVALID_ENCODING`.
- **P15 Estimated costs:**
  - Cost of an assignment = 8 h × the worker's hourly rate from the contract resolved for the roster's month.
  - Shown per shift, per worker and as a monthly total, labelled "estimated". Premiums (night, weekend, overtime) are not modelled.
  - Assignments whose worker has no applicable contract are excluded from totals and counted as "cost unknown".
  - Computed with `Decimal` and rounded to 0.01 ILS for display only.
  - Cost is never part of the solver objective, and cheaper workers are never preferred.

## 6. Main flows and API
Every route is under `/api`. Errors use one shape, `{"error":{"code","message","details"}}`, with these statuses:
- 400, 401, 403, 404
- 409: `VERSION_CONFLICT`, `STALE_PREVIEW`, `ALREADY_CONFIRMED`, `WORKER_IN_USE`, `APPROVED_EDIT_NOT_ACKNOWLEDGED`
- 413: `FILE_TOO_LARGE`, `TOO_MANY_ROWS`
- 415: `/imports` with a content type other than `text/csv`
- 422: validation, a hard violation (with a violations list), `HARD_VIOLATIONS` on approve, or `LOCKED_SHIFT`
- 429: `GENERATION_IN_PROGRESS`
- 500: `ENGINE_ERROR` (engine error, unexpected INFEASIBLE, crashed process pool). Nothing is persisted.

**Shared API contract:**
- The Pydantic schemas in `app/api_schemas/` are written in T0 for the vertical-slice endpoints: meta, the generate outcome, save, and roster read.
- They mirror the engine's result and violation types (§4.5, §4.6); every assignment carries `role`.
- The exported OpenAPI file is committed, and the frontend types are generated from it.
- The remaining endpoints are added to the contract through the main session before each session starts on them (§9).

**Auth**
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- Uses a signed HttpOnly SameSite=Lax session cookie, is same-origin through nginx, and accepts JSON bodies only.
- Seeded users: `planner` and `manager`, passwords documented in the README.

**Workers**
- `GET|POST /workers`, `GET|PATCH|DELETE /workers/{id}`.
- A PATCH that changes role or status needs `expected_version`. The `?preview=true` impact list is deferred (P7).

**Contracts**
- `GET /workers/{id}/contracts` returns all versions plus `resolved_for=YYYY-MM`.
- `POST /workers/{id}/contracts/preview` and `POST /workers/{id}/contracts` (with the preview fingerprint) share the change-set service with CSV.
- Both the contract preview and the CSV preview include `locked_violations`: new hard violations in started shifts, per affected roster. This drives the P2 warning.

**CSV**
- `POST /imports` (raw `text/csv` body, streamed with byte and row limits; P14) returns the preview: each row classified NEW, UNCHANGED, CHANGED or INVALID with errors; old/new diffs; effective month; affected rosters; and an `invalidates_approved` flag.
- `GET /imports/{id}`.
- `POST /imports/{id}/confirm` with `{decisions:{national_id: APPROVE|SKIP}}`.
- `GET /exports/workers.csv?month=`.

Confirm runs in one transaction:
1. Take the advisory lock, then flip `status='CONFIRMED' WHERE status='PENDING'`; if no row changes, return 409.
2. Recompute each approved employee's base fingerprint (worker `row_version` plus latest contract version id) and the affected-roster versions. Any mismatch returns 409 `STALE_PREVIEW` with a fresh preview, and nothing is applied.
3. Insert versions and update workers.
4. Revalidate affected rosters. Approved rosters with hard violations become DRAFT and their approval is revoked (`CONTRACT_CHANGE`, import id). Assignments are kept; nothing is rescheduled.
5. Store the result.

Invalid and skipped rows are never applied. Valid ones are unaffected by them.

**Rosters**
- `GET /rosters/{month}` returns:
  - the roster and its assignments (with `role`)
  - violations, coverage gaps and hour shortfalls
  - estimated costs (per shift, per worker, and the monthly total; P15)
  - approval history
  - `is_history`, `free_from` and `forbid_adjacent_shifts`
- `POST /rosters/{month}/generate` takes `{forbid_adjacent_shifts: bool = false}`:
  - `problem_builder` computes `free_from` from `now_israel()` and loads the stored assignments of started shifts as `fixed_assignments`.
  - It also loads the neighbor months' boundary-day assignments as `neighbor_assignments`, only for boundaries where the rule applies: this roster's flag or the neighbor roster's flag is on.
  - It then runs `solve` in the process pool.
  - The engine outcome (§4.6) is mapped to UI feedback plus estimated costs and a `fingerprint`.
  - Nothing is persisted, so a failed or timed-out run cannot overwrite anything.
- `POST /rosters/{month}/save` takes `{assignments, fingerprint, expected_version|null, replace_existing, forbid_adjacent_shifts}`, and stores the flag on the roster.
  - Under the lock it recomputes the fingerprint: a hash of the worker ids and their row versions, the resolved contract ids, the demand, the roster version, `free_from`, `forbid_adjacent_shifts`, and the neighbor rosters' versions and flags.
    - A mismatch returns 409 `STALE_PREVIEW`. This includes the case where a shift started between generate and save.
  - Assignments in started shifts must equal the stored ones; otherwise it returns 422 `LOCKED_SHIFT`.
  - Replacing an existing roster needs `replace_existing` and the matching version. The UI first shows "replaces N assignments, last edited by X at T".
  - It rejects new or worsened hard violations with 422 (the gate of §4.5, so existing violations in locked shifts do not block). It saves as DRAFT; replacing an approved roster revokes its approval (`REGENERATE`).
- `POST /rosters/{month}/assignments`, `DELETE …/assignments/{id}`, `POST …/assignments/{id}/move`.
  - Every one takes `expected_version` and `acknowledge_approved_edit`.
  - Any of them that touches a started shift returns 422 `LOCKED_SHIFT` (P3).
  - Every one is checked under P10, including adjacency wherever the rule applies.
  - The flag can only be changed by regenerating and saving (replace), never by an edit.
  - A move runs in one transaction: remove plus add, checked together. On failure nothing changes.
- `GET /rosters/{month}/suggestions?date=&shift=&role=` returns candidates. An apply is just the add endpoint, revalidated.
- `POST /rosters/{month}/approve` (MANAGER) takes `{expected_version, acknowledge_warnings, reason, warnings_fingerprint}` (P11).
- `GET /meta` returns shifts, roles, demand, and the documented CSV header and value aliases.

**Suggestions** (`rosters/suggestions.py`, pure, takes a Problem plus assignments):
- A candidate is an active, contracted worker with the right role. Adding them must leave `worsened(before, after)` empty, which includes adjacency where the rule applies.
- Suggestions are offered only for gaps in free shifts.
- Ranked by min-hour deficit (descending), then assigned hours (ascending), then name.
- Each candidate comes with a reason list, e.g. "Screener · available Tue B · 96/160 h (64 h below minimum) · 1 shift that day".
- There are no swap chains, no solver calls, and no cost-based ranking.

## 7. Frontend screens
- **Login.**
- **Workers:** list with filters; create/edit form with inline 422 errors; delete, falling back to a "deactivate" offer on 409. A role/status change shows a simple confirmation (detailed preview deferred, P7).
- **Worker detail:** contract version timeline, the contract resolved for the selected month, and a new-version form, then an impact preview, then confirm.
- **Import:** upload, then a preview grouped as New, Changed, Unchanged and Invalid, showing diffs, effective month and affected rosters. A red banner appears if an approved roster would be invalidated. If `locked_violations` is not empty, the banner adds the P2 locked-violation warning. The preview also lists unknown columns. Per-employee approve/skip, confirm, result summary; a stale preview offers "reload preview".
- **Worker detail contract preview:** shows the same P2 warning when it applies.
- **Export:** month picker.
- **Roster:**
  - Month picker; status badge (none, draft, approved, history).
  - Generate has an option, "Forbid back-to-back shifts (optional rule)", which is off by default. The badge shows the rule when it is on.
  - Generate shows a spinner and the 429 message, then a preview with the solver outcome in plain language, gaps, shortfalls and estimated costs, then "Save as draft" (with a replace confirmation).
  - Grid: rows are days, columns are shifts A/B/C. Each cell has five role slots holding names, or gap buttons, plus the cell's estimated cost.
  - Started shifts in the current month are shown as locked. Their gaps are shown as past, not as fillable.
  - An assignment opens a remove/move dialog. A gap opens the suggestions panel.
  - Side panel: violations, gaps, shortfalls, estimated monthly cost (total and per worker, with any "cost unknown" count), approval (manager only), history.
  - Editing an approved roster asks for confirmation first.
- **Common states:** loading skeletons; 401 goes to login; 403 shows a message; 409 offers "data changed, reload"; network errors show a toast.

**Plain-language outcomes:**
| Engine outcome | Message |
|---|---|
| Solved, lexicographically optimal | "Best possible roster" |
| Coverage proven (`lower_bound − locked_uncovered ≥ 1`) | "At least k upcoming positions cannot be filled with current contracts" |
| Coverage FEASIBLE | "Best found within the time limit; at least L upcoming positions cannot be filled" (omitted when L = 0) |
| Minimum hours FEASIBLE | "Minimum hours not proven optimal within the time limit" |
| `NoSolutionWithinLimit` | "No roster found in time; nothing was changed" |
| `EngineError` / `InvalidInput` | Error panel with details |

## 8. Tasks (dependency order)
★ marks a review checkpoint. The first milestone is a thin end-to-end vertical slice. The plan then expands to the full submission: every mandatory requirement plus the two bonus features (D7). Git branches and commits follow §9.

| # | Task | Owns | Context | Acceptance / tests |
|---|---|---|---|---|
| T0 | Skeleton and shared contracts | compose, Dockerfiles, `app/main,config,db,errors`, `scheduling/types.py` (Assignment with role, Violation with key/magnitude, Problem, results; frozen), `app/api_schemas/` for the slice endpoints, OpenAPI export plus TS type generation, frontend scaffold | §2, §4.2, §4.5, §4.6, §6 | A clean `docker compose up` gives a healthy `/api/health` and serves the frontend. The error-shape test passes. The OpenAPI file is committed and the generated TS types compile |
| T1 | Scheduling engine | `app/scheduling/`, `tests/scheduling/`, `bench/` | §4 | All tests in §4.9 pass; the benchmark table (§4.8) is produced from the actual model |
| T2 | DB schema, auth and seed | `alembic/`, `app/*/models.py`, `app/auth/`, seed (users plus sample workers/contracts) | §3, P12 | Migration from empty works. The immutability trigger rejects UPDATE/DELETE. Constraint tests cover the ID regex, min≤max and unique month. Login/me/logout work; `require_role` returns 403. The seed is idempotent |
| T3 | Roster slice backend | `app/contracts/` resolution (read path), `app/rosters/{problem_builder,evaluation,generation,save,costs}.py`, `approval.revoke` | §3, §4.2, §4.5, §4.6, §6 rosters, P3, P4, P15 | Resolution: past, current and future months, same-month supersede, no contract. Problem builder: inactive, no contract, `free_from` from a frozen clock (before midnight, mid-shift, exactly at a shift start), fixed from stored started shifts, neighbor-month assignments passed only where the adjacency rule applies (this roster's flag, the neighbor's flag, neither). Save stores `forbid_adjacent_shifts`, and a flag mismatch against the fingerprint gives 409. Generate returns each outcome type, and a failure never persists. Save: fingerprint mismatch gives 409, including a shift that started between generate and save; a changed started shift gives 422 `LOCKED_SHIFT`; replace needs the flag and version; new hard violations give 422, while existing ones in locked shifts do not. Costs: per shift/worker/month, missing contract counted as unknown, `Decimal` rounding. The busy guard returns 429 and is released after success, error and cancellation. Mocked INFEASIBLE gives 500 `ENGINE_ERROR`, and the existing roster is unchanged. Pool recovery: a mocked `BrokenProcessPool` gives 500 `ENGINE_ERROR`, and the next generation succeeds on a new executor. Two callers that fail on the same broken executor cause exactly one replacement (identity check). Warm-up runs in the child and imports `ortools`; a warm-up failure shows as `engine: not_ready` on `/api/health` |
| T4 | Frontend slice | `frontend/src/{api,auth,layout,errors}`, `frontend/src/features/roster` (read, generate, save) | §6 contract, §7 | Generated types compile. Login and the 401 redirect work. The error mapper has a unit test. Manual walkthrough on seeded data: pick a month → generate → grid shows assignments, gaps, shortfalls and costs → save as draft |
| ★M1 | Vertical slice works end to end on a clean `docker compose up` | | | |
| T5 | Workers, contract versions and change-set service (backend and UI) | `app/workers/`, `app/contracts/` (write path), `app/changes/` (incl. `worker_field_history`), `frontend/src/features/workers` | §6, P1, P2, P5, P6, P7, D9 | Israeli-ID checksum valid/invalid cases. CRUD and the 409 on in-use delete. A version-conflict test. Contract change impact lists the affected rosters. Apply keeps assignments, sends invalid approved rosters to draft (`CONTRACT_CHANGE`) and keeps the revoked approval row. A role/status change does the same with `WORKER_CHANGE`, records a `worker_field_history` row, and is checked with `resolve_worker_state`: deactivating (or changing the role of) a worker with an already-started shift this month leaves that shift's `INACTIVE_WORKER`/`WRONG_ROLE` status unchanged (no new violation), while an upcoming shift is affected immediately. A worker already inactive (or in a different role) before the shift started still shows the violation. Stale base gives 409 with nothing applied. The P2 warning: a retroactive change that creates a hard violation in a started shift returns `locked_violations` in the preview, and after apply the roster stays unapproved with the violation visible. A same-month correcting version (P1) removes the violation, and both versions stay in history. A change that creates violations only in free shifts returns an empty `locked_violations` |
| T6 | CSV import/export and sample data (backend and UI) | `app/csvio/`, `sample-data/`, `frontend/src/features/imports` | §6 CSV, P8, P9, P13, P14 | Partial success: invalid rows do not block valid ones. Duplicate-in-file handling. Repeated confirm gives 409. Stale gives 409. A confirmed import that invalidates an approved roster sends it to draft with `CONTRACT_CHANGE` and the import id. Round trip: an unmodified export gives all UNCHANGED.

Review-CSV support:
- **Header matching:** columns in a shuffled order and header aliases (`Name`, `Israeli ID`, `Hourly Cost`) are matched. A missing required column gives 400 `MISSING_COLUMNS`. Duplicate normalized headers give 400. Unknown columns become a warning.
- **Optional columns and worker-only rows:** a missing `status` defaults to ACTIVE, and a missing `effective_month` defaults to the current Israel month (frozen clock), shown resolved in the preview (D11). A row with every contract column empty imports as worker-only, with no contract version (D10). A row with only some contract columns empty gives `INCOMPLETE_CONTRACT`.
- **Role and status aliases:** `General Guard`, `general-guard` and `Guard` map to GENERAL_GUARD. Mixed-case `Screener`, `Supervisor`, `Active` and `Inactive` are accepted. An unknown role is INVALID.
- **Availability:**
  - `available_days=Sun|Mon` with `available_shifts=A|C` gives exactly the 4 pairs.
  - Full day names, `Morning/Day/Evening` and `AC` are accepted.
  - A quoted comma-separated value is accepted.
  - Both forms filled: `AMBIGUOUS_AVAILABILITY`. Only one of the pair: `INCOMPLETE_AVAILABILITY`. Empty: `MISSING_AVAILABILITY`. An unknown token is named in the error.
  - The same availability in either form classifies as UNCHANGED.
- **IDs:**
  - `012345674`-style IDs with a leading zero are kept as strings.
  - 8 digits gives INVALID `ID_LENGTH` with the leading-zero hint, and nothing is padded.
  - `1.23E+08` gives `ID_FORMAT`.
  - A bad checksum is INVALID.

Formula protection and round trip:
- **External rows** (no `export_format` column, or an empty value): `=x`, `+x`, `-x`, `@x`, `'Neil` and `'=x` are all stored verbatim. No apostrophe is removed.
- **Export:**
  - Names starting with `=`, `+`, `-`, `@`, TAB, CR or `'` are written with one leading `'`.
  - Every row has `export_format=icts-export-v1`.
  - Availability is written in the per-day form.
- **Export rows:** `''Neil` becomes `'Neil`, `'=x` becomes `=x`, and `'Neil` (no trigger after the apostrophe) stays `'Neil`.
- **Round trips from both sources:** names first imported from an external file (including `'Neil` and `'=x`) and names created in the UI both export and re-import to the identical name with status UNCHANGED.
- **Mixed file:** an export file with extra appended rows that leave `export_format` empty treats those rows as external. `export_format=other` is INVALID `UNKNOWN_EXPORT_FORMAT`.

Limits:
- exactly 1 MB is accepted
- 1 MB + 1 byte gives 413 `FILE_TOO_LARGE`, and the stream is not read past the limit plus one chunk (tested with a counting stream)
- an oversized `Content-Length` is rejected before reading
- 5,000 data rows are accepted
- 5,001 rows give 413 `TOO_MANY_ROWS`, with nothing stored
- invalid UTF-8 gives 400
- a `multipart/form-data` request gives 415

Sample data (D5): the sample CSV starts at 23 workers (9 GG, 9 SCR, 5 SUP). An integration test generates a 28-day, a 30-day and a 31-day month from it. It requires OPTIMAL with 0 gaps and 0 shortfalls under all constraints (availability, daily limit, min/max hours), with the adjacency rule both off and on. If it fails, add workers until it passes. The separate shortage fixture creates proven supervisor gaps |
| T7 | Manual edits and suggestions (backend and UI) | `app/rosters/{edits,suggestions}.py`, roster edit UI | P10, §6 | Add/remove/move valid cases. A failed move leaves the original intact. Rejected edits: a new violation, and a worsened one (same key, higher magnitude). With the rule on, adjacency is rejected within a day, across days, and across a month boundary against the neighbor roster. With the rule off, A+B is accepted. A boundary pair is still rejected when the neighbor roster has the rule on. Add, remove and move on a started shift give 422 `LOCKED_SHIFT`. Removal from a free shift is allowed on an invalid roster. Editing an approved roster needs the acknowledgement and goes to draft with history kept. Suggestions (bonus feature 2): eligibility (including adjacency where the rule applies), no suggestions for started shifts, ranking, reasons, and an apply that is revalidated. **Neighbor-month `row_version`:** every edit (add, remove, move, apply-suggestion) increments `rosters.row_version` in the same transaction. The generate/save fingerprint includes the neighbor rosters' `row_version` (T3), so a test must show that an edit to the adjacent month's roster changes the fingerprint and makes a save that was previewed before the edit fail with 409 `STALE_PREVIEW` |
| T8 | Approval (backend and UI) | `app/rosters/approval.py`, approval panel | P11, P12 | A planner gets 403 and a manager succeeds. Hard violations give 422 `HARD_VIOLATIONS` even with `acknowledge_warnings=true` and a reason, including a hard violation in a started shift. Soft shortages without an acknowledgement and reason give 422. Soft shortages with an acknowledgement, a reason and a matching `warnings_fingerprint` are approved, with the snapshot stored. A stale `warnings_fingerprint` gives 409. A roster with no shortages is approved without an acknowledgement. Approver and time are recorded. Version conflict gives 409. Audit trail (bonus feature 1): the approval history lists every approval and revocation with actor, time, roster version, reason, acknowledged-warnings snapshot, and revoke cause and reference (EDIT, REGENERATE, CONTRACT_CHANGE with the import or version id, WORKER_CHANGE), in order. Automatic invalidation through each of those four causes is covered end to end. **Schema dependency:** the T3 `ApprovalEventOut` (frozen in T0) has only `approved_by`, `approved_at`, `reason`, `revoked_at` and `revoke_cause`. T8 extends it with `roster_version`, `acknowledged_warnings`, `revoke_ref` and `revoked_by` (the columns already exist in `roster_approvals`), regenerates `openapi.json` and the frontend types, and keeps `GET /rosters/{month}` returning them in order |
| ★M2 | Full submission feature-complete | | | |
| T9 | End-to-end and README | `README.md`, `tests/e2e/` (httpx against the running stack) | everything | Clean database, compose up, scripted flows pass. README covers architecture, schema, indexes, setup, CSV format, feature value, assumptions, trade-offs and limitations. It also covers:
- the scheduling design, including the weight derivation, the timeout limitations, and the small and scale benchmark results with their time budget and hardware
- the adjacency rule as an optional setting, off by default, so the defaults match the brief
- costs as core estimates
- the CSV header and value aliases, both availability forms, and the export marker and escaping convention
- a rationale for each bonus feature (§10) |
| ★M3 | Final | | | |

Backend tests run with pytest against a Postgres test database in compose, with each test rolled back.

### Status after T5 and T7
T5 (workers, contract versions, change-set service) and T7 (manual edits, suggestions) are merged. Carry-over for the remaining tasks:
- **T6 reuses** `app/changes/service.py` (`preview_change_set` / `apply_change_set`, so a confirmed import is one change set) and `app/contracts/availability.py`. Availability is stored in MON..SUN then A..C order, matching the seed, not lexicographic order. The CSV import must use the same helper so an unchanged row classifies as UNCHANGED.
- **T8 must know** that a change-set apply that revokes an approval also bumps that roster's `row_version` (it feeds the save fingerprint), and that edits (T7) already revoke with cause `EDIT` through `approval.revoke`. Revoke references are `contract_version:{id}` and `worker:{id}`; T6 will add the import id.
- The seed supervisor's national ID was changed to a checksum-valid `555555556`. An existing database volume keeps the old ID until `docker compose down -v`.
- `GET /rosters/{month}/assignments` exists because `RosterOut.assignments` has no id. An optional `id` on the roster read would remove the client-side join (T9 polish, optional).
- Deferred: the detailed role/status impact preview (P1). The UI asks for a plain confirmation.

### Status and carry-over after M1 integration (T3 + T4)
Done in the integration of T3 and T4: `YYYY-MM` month validation (422 in the §6 error shape), a `workers` name lookup and `updated_at`/`updated_by` on the roster read, `CostsOut.per_shift`, the `NO_CONTRACT_FOR_MONTH` violation code, error and logout responses documented in `openapi.json`, frontend types generated from it, and the frontend TypeScript pinned to 5.9 so `openapi-typescript` installs without `legacy-peer-deps`.

Known engine and app limitations from T3. None blocks the M1 flow (login, month, generate, grid, save draft, reload, replace), which was run against the real stack. Each has an owner:
| Limitation | Effect | Owner |
|---|---|---|
| Cancelling a generate request releases the busy guard, but the spawned solve keeps running | The next generation queues behind it on the single worker process, up to the solver time limit | T9 (document in the README limitations; fix only if it shows in the end-to-end run) |
| Engine warm-up is not retried after a failure | `/api/health` stays `engine: not_ready` until a pool crash replaces the executor | T9 (README limitation, or retry on the next generate) |
| The DB session stays open during the solve | One pooled connection is held for up to the time limit per generation. Only one generation runs at a time, so the pool cannot be exhausted | Accepted |
| `ApprovalEventOut` lacks version, snapshot, revoke reference and revoker | The audit trail cannot be shown yet | T8 (see its acceptance) |
| Neighbor-roster edits must bump `row_version` | Otherwise the fingerprint would not detect an adjacent-month edit | T7 (see its acceptance) |
| The seed has 5 workers | A generated month shows most positions as gaps. The 23-worker sample data (D5) arrives with T6 | T6 |
| The month picker resets to the current month on page reload | The selected month is not kept in the URL | T9 polish, optional |


## 9. Parallel sessions (at most two)
- **T0** runs as a single session. It freezes the shared contracts: engine types and slice API schemas.
- **After T0:**
  - Session S: T1, then T3 (T3 needs T1 and T2)
  - Session A: T2, then T4 (T4 builds against the committed OpenAPI contract and switches from mocked responses to the live API when T3 lands)
- **After M1:**
  - Session S: T5, then T6
  - Session A: T7, then T8
  - The shared contract is `rosters.evaluation.evaluate(session, roster)`, `approval.revoke(...)` and the engine's `worsened(...)`, all in place after T3.
- **T9** runs as a single session.

**Git history** (the brief says branch structure and commit history are observed):
- **One feature branch per coherent unit of work,** created from `main`:
  - `feat/skeleton` (T0)
  - `feat/engine` (T1)
  - `feat/db-auth-seed` (T2)
  - `feat/roster-slice` (T3 + T4)
  - `feat/workers-contracts` (T5)
  - `feat/csv` (T6)
  - `feat/edits-suggestions` (T7)
  - `feat/approval` (T8)
  - `docs/readme-e2e` (T9)
  - Plan changes go on `docs/plan-*` branches.
- **Commits** are focused and descriptive, in Conventional Commits style (`feat(engine): …`, `test(csv): …`, `docs: …`). Each commit leaves the tests it touches passing.
- **Merging:** when pushing is allowed, a PR may group related branches. A PR per small task is unnecessary. Merges into `main` use `--no-ff`, so each feature stays visible in the history.
- Until then, branches are merged locally the same way. **Nothing is pushed until you say so.**

**Ownership:**
- Each session edits only the modules it owns. Changes to shared files (`models`, `errors`, `scheduling/types.py`, `api_schemas`, OpenAPI) go through the main session. A session's new endpoints are added to the contract before it starts on them.

## 10. Scope priorities
- **P0, first (vertical slice, M1):** compose startup with seeded data, login, month picker, generate, grid with assignments, gaps, shortfalls and costs, save draft.
- **P0 (must ship, M2):**
  - **Core (brief §2.1–2.4 and §3–4):**
    - workers CRUD with ID validation
    - immutable contract versions and resolution
    - CSV preview/confirm with partial success, review-CSV support (P14) and the export round trip
    - engine (§4), with fixed assignments, the optional adjacency rule and the small and scale benchmarks
    - unfillable-shift and per-worker shortfall alerts before saving
    - grid
    - add/remove/move with the repair rule (keys and magnitudes)
    - **estimated costs** (core, since the brief says the hourly cost is "used for cost estimation")
    - compose startup
    - README
    - sample data (≥ 10 workers)
    - the focused backend tests listed above
  - **Bonus feature 1: manager approval with automatic invalidation and an audit trail.**
    - Planner/manager roles and approval (P11, P12).
    - Automatic revocation on edit, regeneration, contract change (UI or CSV) and worker change.
    - Approval history recording actor, time, version, reason, acknowledged snapshot and revoke cause.
    - The audit trail covers approval events. It is not a log of every edit.
    - Rationale: no roster goes live without sign-off, and no signed-off roster silently becomes invalid.
  - **Bonus feature 2: gap-fill suggestions with reasons.**
    - For any unfilled free slot: ranked eligible candidates, each with human-readable reasons, applied in one click and revalidated (§6).
    - Rationale: turns "shift X cannot be filled" into a fast, explained fix, and prioritizes workers below their contracted minimum.
- **P1:** detailed impact preview for worker role/status edits, Hypothesis property-based engine tests, frontend unit tests beyond the error mapper, full end-to-end script.
- **P2 (cut first):** drag and drop, Playwright, rich history views, preview expiry.

## 11. Engine/application integration (resolved)
- **C1 Slot role on assignments:** adopted. `Assignment` carries `role` everywhere (engine, API, database), and the validator checks it against the worker's role.
- **C2 Violation keys and magnitudes:** adopted (§4.5). The engine's validation gate, P10 manual edits and suggestions all use `worsened(before, after)`.
- **C3 Workers not in the engine input:** the engine reports them as `UNKNOWN_WORKER`. The application maps that to `NO_CONTRACT_FOR_MONTH`. No engine change.

## 12. Decisions needed from you
**Resolved**
- **D1 Repository:** https://github.com/LinaKoz/ICTS, cloned to `/Users/koz/icts-rostering`. The plan lives at `docs/plans/application.md`.
- **D4 Demo credentials:** option (b). Environment configuration, with demo defaults in `.env.example` and the credentials documented. See §2 for details.
- **D5 Sample data:** start with 23 workers (9 GG, 9 SCR, 5 SUP) and verify feasibility under all constraints with the T6 integration test. Add workers if it fails. The shortage fixture stays separate.
- **Finding 8 (process pool):** approved. `spawn`, a warm-up that imports the solver, coordinated pool replacement, and the guard released in `finally` (§2, T3).
- **Finding 9 (CSV):** approved. Formula escaping is limited to exported rows, identified by a source marker; external names are never unescaped. A 1 MB limit is enforced while reading a raw `text/csv` stream, and a 5,000-row limit while parsing (P14, T6).
- **Adjacency rule:** option (b). A per-roster optional setting, off by default (§4.1).
- **Scale benchmarks:** 200, 500 and 1,000 workers under a documented time budget (§4.8).
- **Review-CSV support:** header matching, aliases, the `available_days` + `available_shifts` form, and string IDs with no padding (P14).
- **Git history:** feature branches per unit of work, with focused commits (§9). No push yet.
- **Costs:** core scope (§10).
- **D7 Bonus features:** (1) manager approval with automatic invalidation and an audit trail, and (2) gap-fill suggestions with reasons (§10). Checked against brief §2.5, which requires at least 2 features that "extend the Rostering or HR platform in a meaningful way", deliver "genuine operational value", are "fully implemented", and have a README rationale:
  - **Approval:** not part of the mandatory §2.1–2.4 (the brief mentions no approval, sign-off or user roles). It qualifies.
  - **Suggestions:** §2.4 already requires manual moving and adding, so the plain add action is core. The bonus is the ranked candidates with reasons and the one-click apply, which go beyond the mandatory manual editing. It qualifies, provided the README and demo present it as distinct from manual add.
  - **Condition for both:** "fully implemented" means API, UI and tests (T7, T8), plus the README rationale (T9).
- **D8 Hard violations in started shifts:** started shifts are immutable, and violations stay visible and block approval. Wrong data is corrected through versioning; genuine violations leave the roster unapproved, with no bypass. A focused warning appears before confirming (P2, P3, P11).
- **D9 Worker status/role changes mid-month:** option (b). `worker_field_history` (§3) records every status/role change with an effective timestamp. Locked (already-started) shifts are checked against the worker's status/role as of when the shift started (`resolve_worker_state`), not the current value, so a mid-month deactivation or role change never retroactively invalidates a shift already worked. Upcoming shifts always use the current value.
- **D10 P13 versus the brief:** accepted. Export includes every worker; one with no applicable contract gets empty contract columns and is counted separately as "no contract" rather than skipped. Import accepts a worker-only row with every contract column empty and creates or updates the worker with no new contract version.
- **D11 Review-CSV defaults:** accepted. A missing `status` column or empty cell defaults to ACTIVE; a missing `effective_month` column or empty cell defaults to the current Israel month. Both resolved values are shown in the preview rather than left blank.

**D2 policies: all of P1–P15 are accepted.**
- **Accepted as written:** P1 (same-month revisions), P4 (worker without a contract excluded and flagged), P5 (identical data creates no version), P6 (delete), P8 (duplicate IDs in a file INVALID), P9 (repeated confirm, 409 with stored result), P12 (two roles).
- **Accepted with amendment:** P2 (retroactive changes, with the D8 locked-violation warning), P3 (history lock; started shifts immutable), P7 (status/role changes; locked shifts use `resolve_worker_state`, D9), P10 (repair rule using keys and magnitudes, `worsened(before, after)`), P11 (only soft shortages can be acknowledged; hard violations never can), P13 (D10: full export, worker-only rows), P14 (D11: defaulted `status`/`effective_month`), P15 (estimated costs, core).

**Open**
- None. All of D1–D11 and P1–P15 are resolved.
