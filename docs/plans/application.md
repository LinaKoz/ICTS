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
| Our choice (product decision) | Back-to-back shifts are forbidden: A→B, B→C, and C→next-day A. A+C on the same day is allowed. The maximum of 2 shifts per calendar day stays. This is a product decision, not a claim of labor-law compliance |
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
- **Generation execution:**
  - The engine runs in a `ProcessPoolExecutor(max_workers=1)` via `run_in_executor`, so CPU work never blocks the API event loop or other requests.
  - A non-blocking process-local guard allows one generation at a time. A second request gets 429 `GENERATION_IN_PROGRESS`.
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
| `rosters` | id, month date, status (DRAFT, APPROVED), row_version, generation_meta jsonb, updated_at/by | month UNIQUE, CHECK day=1 |
| `roster_assignments` | id, roster_id FK CASCADE, worker_id FK RESTRICT, date, shift, role (the slot role, snapshotted) | UNIQUE(roster_id, worker_id, date, shift); index (roster_id, date, shift); index (worker_id) |
| `roster_approvals` | id, roster_id, roster_version, approved_by, approved_at, acknowledged_warnings jsonb, reason, revoked_at, revoked_by, revoke_cause (EDIT, REGENERATE, CONTRACT_CHANGE, WORKER_CHANGE), revoke_ref | index (roster_id, approved_at DESC) |

**Contract resolution** for month M: `effective_month ≤ M`, ordered by `effective_month DESC, version_no DESC`, first row. A future version can never resolve for an earlier month. There is no current-contract pointer, and the UI's "current contract" means resolved for the current Israel month.

**Violations, warnings and costs** are never stored. `rosters.evaluation` computes violations and warnings on read with the engine's `validate_roster` / `roster_metrics` (§4.2) against the current data. `rosters.costs` computes estimated costs on read (§6). Workers without an applicable contract become violation `NO_CONTRACT_FOR_MONTH` in the application layer.

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
- **Adjacent shifts (product decision):**
  - A→B and B→C on the same day, and C on day d → A on day d+1, are back to back and forbidden.
  - A+C on the same day is allowed.
  - The rule applies to generation, manual edits and the validator, including pairs that cross a month boundary.
  - It is a product decision, not a claim of labor-law compliance.
- **Locked and free shifts:**
  - `free_from` is a `(date, shift)` position in the month. Shifts before it are locked; shifts at or after it are free.
  - The application sets `free_from` to the first shift whose start time is after `now_israel()`. A shift that has started is locked.
  - For a future month, `free_from` is `(1st, A)`. A fully locked month uses `(last day + 1, A)`.
  - Stored assignments in locked shifts are passed in as `fixed_assignments` and returned unchanged. The solver assigns free shifts only.
- **Neighbor-month assignments:**
  - These are the stored assignments on the previous month's last day and the next month's first day, if those rosters exist.
  - They are read-only and used only for the adjacency rule: a C shift on the previous month's last day blocks A on the 1st, and an A shift on the next month's 1st blocks C on the last day.
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
    neighbor_assignments: Sequence[Assignment] = ()      # previous month's last day and next month's first day

@dataclass(frozen=True)
class SolverConfig:
    time_limit_s: float = 10.0  # CP-SAT search time for the single solve
    num_workers: int = 8        # the application passes min(8, cpu_count)
    random_seed: int = 0

def solve(problem, config) -> ScheduleResult
def validate_problem(problem) -> list[InputError]
def validate_roster(problem, assignments) -> list[Violation]   # includes adjacency with neighbor_assignments
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
  - no fixed or neighbor assignment of w is adjacent to `(d,s)`

  Eligibility is checked against the current data for new assignments only. Fixed assignments are never re-checked.
- **Monthly limit:** `new_hours_w ≤ max(0, max_hours_w − fixed_hours_w)`, which is `Σ x[w,·,·] ≤ floor(max(0, max_hours_w − fixed_hours_w) / 8)`.
- **Daily limit:** `Σ_s x[w,d,s] ≤ max(0, 2 − fixed_day(w,d))`. A day can hold both fixed and free shifts; for example, at 10:00 shifts A and B are locked and C is free.
- **Adjacency:**
  - For free pairs: `x[w,d,A] + x[w,d,B] ≤ 1`, `x[w,d,B] + x[w,d,C] ≤ 1`, and `x[w,d,C] + x[w,d+1,A] ≤ 1`.
  - Pairs that involve a fixed or neighbor shift are handled by not creating the variable (above).
  - A fixed pair that is already adjacent stays as it is and is reported.
- **No overstaffing:** `Σ_{w∈r} x[w,d,s] ≤ max(0, demand_of(s,r) − fixed_slot(d,s,r))`. Free slots have no fixed assignments today, but the rule is written generally.
- **Duplicates:** there is at most one variable per `(w,d,s)` and none where a fixed assignment exists.
- **Invariant:** setting every `x` to 0 is always feasible. INFEASIBLE therefore signals a bug.
- **Not enforced, by design:** rest rules beyond the adjacency ban. For example, C followed by the next day's B (an 8-hour gap) is allowed.

### 4.4 Objective (one weighted solve)
**Terms** (active workers in the input only; free slots only):
- `uncovered[d,s,r] = max(0, demand_of(s,r) − fixed_slot(d,s,r)) − Σ_{w∈r} x[w,d,s]`, which is ≥ 0 by the overstaffing rule
- `short[w] ≥ min_hours_w − 8·Σ x[w] − fixed_hours_w`, with `0 ≤ short[w] ≤ min_hours_w`

**Weight:** `S_max = Σ min_hours_w` over active workers, and `W = S_max + 1`.

**Minimize** `W · Σ uncovered + Σ short`.

Coverage gaps in locked shifts are the same in every solution. They are left out of the model as `locked_uncovered` and added back from `roster_metrics`.

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
- **Reported value:** `coverage.lower_bound = locked_uncovered + max(LB_free, diagnostic LB over free slots)`. Both terms are valid bounds.
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

`ADJACENT_SHIFTS` also covers pairs formed with neighbor-month assignments; the key names the earlier shift, which may be in the neighbor month.

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

### 4.7 Diagnostics (`diagnose`, pure and cheap, active workers, free shifts only)
**Proven facts** (lower bounds that hold in every solution):
- **Slot deficit:** `eligible(slot) < remaining demand`. That slot is missing at least the difference in every solution.
  - Eligible means a variable would exist for the worker (§4.3) and the worker has remaining monthly capacity of at least 1.
- **Worker capacity:** `cap_w = min(remaining_max_shifts_w, Σ_free d day_cap(w,d))`.
  - `day_cap = min(max(0, 2 − fixed_day(w,d)), largest non-adjacent subset of w's eligible free shifts that day)`. The subset has size 2 only for {A, C}.
  - Cross-day adjacency is ignored, so this is a relaxation: weaker, never wrong.
- **Role deficit:** if `Σ_{w∈r} cap_w < remaining demand_r`, role r has at least the difference uncovered.
- **Role lower bound:** `LB_r = max(Σ slot deficits in r, role deficit)`. The total diagnostic lower bound is `Σ_r LB_r`.
- **Worker shortfall:** if `8·cap_w + fixed_hours_w < min_hours_w`, that worker's shortfall is at least the difference.
- **From the solver:** the bound described in §4.4.

**Suspected causes:**
- In each gap, `proven_missing` is the slot-deficit part. Any gap beyond it is labelled `SUSPECTED`, with a hint such as "eligible workers at max hours, at the daily limit, or blocked by an adjacent shift".
- A proven minimum gap count does not mean these particular slots must stay unfilled in every solution, so gap locations are never presented as proven.
- Proving that a specific slot can never be filled would need a separate solve per slot; that is out of scope.

### 4.8 Benchmarks (`backend/bench/`)
Benchmarks run on the actual model (adjacency, fixed assignments, neighbor assignments, weighted objective).

A seeded generator builds 30- and 31-day months with `DEFAULT_DEMAND`:
- **comfortable:** about 40 workers
- **tight:** capacity ≈ demand
- **short:** too few supervisors
- **fragmented:** sparse availability
- **min-hours pressure:** high minimums
- **with inactive workers**
- **mid-month:** `free_from` on day 15 at shift B, with fixed assignments from an earlier solve
- **retroactive conflict:** fixed assignments that exceed the reduced `max_hours` or violate the current availability
- **neighbor months:** C shifts on the previous month's last day and A shifts on the next month's first day

Each run records status, model-build time, search time, total elapsed time, objective, bound, the derived coverage lower bound and `total_uncovered`. The README reports the results as measured.
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
- One test per violation code in §4.5, plus a valid roster. Adjacency covers A→B, B→C, C→next-day A, and C on the previous month's last day → A on the 1st (via neighbor assignments).
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
- one supervisor for a 3-shift demand: at most A+C a day, the gap equals demand minus capacity, and it is proven
- adjacency: an instance that could only be fully covered with back-to-back shifts leaves a gap; no adjacent pair appears in the output
- weight sufficiency: covering one extra slot costs the largest possible shortfall increase, and coverage still wins. The fixture is built so that a weight of 1 would pick the other roster; the hand-computed values are in the test docstring
- among coverage-optimal rosters, the one with minimum shortfall is returned
- greedy trap: most-constrained-first greedy leaves a gap, but CP-SAT covers everything
- an inactive worker with a high minimum: no assignments, no shortfall, not counted in capacity
- tiny brute-force check: `free_from` leaves 2 free shifts and 2 workers. Every roster is enumerated, and the solver's `(uncovered, shortfall)` equals the lexicographic minimum

**Fixed assignments and existing violations**
- **Retroactive cap reduction:**
  - fixed 80 h, `max_hours` lowered to 64: `Solved`, no new assignments for that worker, `MAX_HOURS` magnitude stays 16 and is listed, and the gate accepts
  - fixed 56 h with a 64 h maximum: at most 1 new shift
- **Adjacency to a fixed shift:**
  - fixed B on day d (started, C free): the worker is not assigned C on d
  - fixed C on day d−1: the worker is not assigned A on d
  - fixed A on day d: C on d is allowed
- **Neighbor months:** C on the previous month's last day blocks A on the 1st; A on the next month's 1st blocks C on the last day.
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
- `day_cap` respects adjacency and fixed shifts
- inactive workers are excluded
- gaps beyond `proven_missing` are marked `SUSPECTED`
- the diagnostic lower bound is ≤ `total_uncovered` on every solver fixture

**Independence**
- The engine never imports sqlalchemy, fastapi, or any `app.*` module outside `scheduling`. Checked by an import-linter contract or a test.

**Deferred (P1):** Hypothesis property-based tests on random small instances.

## 5. Application policies (all proposed; confirm them in D2)
- **P1 Same-month revisions:** allowed. A new version with the same `effective_month` supersedes the earlier one because its `version_no` is higher. Both are kept.
- **P2 Past effective months:** allowed. The preview labels them "retroactive" and lists the affected rosters.
- **P3 Historical rosters and locked shifts:**
  - Rosters for months before the current Israel month are read-only history. They are not revalidated, edited, regenerated or approved, and are shown without violation evaluation.
  - In the current month, regeneration keeps every shift that has already started (§4.1) and reschedules only future shifts.
- **P4 Active worker without an applicable contract:** excluded from engine input and suggestions. The generation preview lists them ("no contract for 2026-11"). Existing assignments show `NO_CONTRACT_FOR_MONTH`.
- **P5 Identical data:** a contract whose fields (rate, min, max, availability) equal the version resolved at the row's effective month creates no version. Worker fields unchanged means no update.
- **P6 Worker deletion:** hard delete only if the worker has no contract versions and no assignments. Otherwise the API returns 409 `WORKER_IN_USE`, and the UI offers "deactivate" instead. History is preserved.
- **P7 Status and role changes** (not month-versioned):
  - Applying one revalidates the affected rosters (current and future months that contain the worker). Approved rosters that gain hard violations return to draft and their approval is revoked (`WORKER_CHANGE`), the same as for contract changes.
  - Assignments keep their snapshotted slot role, so a role change shows up as a `WRONG_ROLE` violation. Nothing moves silently.
  - The detailed impact preview before apply (the list of affected rosters) is deferred (P1). Until then the UI shows a simple confirmation.
- **P8 Duplicate national IDs in one file:** every row with that ID is INVALID (`DUPLICATE_IN_FILE`). Other rows are processed.
- **P9 Repeated confirmation:** the second confirm returns 409 `ALREADY_CONFIRMED` with the stored result. Nothing is applied twice.
- **P10 Incremental repair rule** (manual edits):
  - Uses the violation keys and magnitudes of §4.5 and the engine's `worsened(before, after)`. It is never simplified to counts.
  - An edit, including a move as remove+add, is accepted only if `worsened(before, after)` is empty. Adjacency is checked against neighbor-month rosters too.
  - A removal always passes. Coverage and hour warnings never block.
  - Generation and manual edits on a clean roster therefore enforce all hard constraints. Only contract/worker changes may introduce violations.
- **P11 Approving with warnings:** a manager may approve despite coverage or min-hour warnings only with `acknowledge_warnings=true` and a non-empty reason, both stored. Hard violations always block (422).
- **P12 Permissions:**
  - PLANNER: workers, contracts, CSV import/export, generation, drafts, edits. Editing an approved roster needs an explicit acknowledgement and returns it to draft.
  - MANAGER: everything a planner can do, plus approve.
  - The worker role SUPERVISOR is unrelated to app permissions.
- **P13 Export version:** one row per worker with the version effective for the chosen month (default: the current month), otherwise the next future version. Workers with no contract at all are skipped and counted in the response. Rows carry the version's own `effective_month`, so re-importing an unmodified export gives all rows UNCHANGED.
- **P14 CSV format:**
  - Encoding: UTF-8 (a BOM is accepted on import and written on export, for Hebrew in Excel).
  - A header row is required. Columns: `national_id, full_name, role, status, effective_month (YYYY-MM), hourly_rate_ils, min_monthly_hours, max_monthly_hours, availability`.
  - Availability looks like `MON:AB|TUE:ABC|FRI:C`.
  - The ID must be exactly 9 digits and pass the checksum; there is no auto-padding.
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
- 422: validation, a hard violation (with a violations list), or `LOCKED_SHIFT`
- 429

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

**CSV**
- `POST /imports` (multipart) returns the preview: each row classified NEW, UNCHANGED, CHANGED or INVALID with errors; old/new diffs; effective month; affected rosters; and an `invalidates_approved` flag.
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
  - `is_history` and `free_from`
- `POST /rosters/{month}/generate`:
  - `problem_builder` computes `free_from` from `now_israel()`. It loads the stored assignments of started shifts as `fixed_assignments`, and the neighbor months' boundary-day assignments as `neighbor_assignments`.
  - It then runs `solve` in the process pool.
  - The engine outcome (§4.6) is mapped to UI feedback plus estimated costs and a `fingerprint`.
  - Nothing is persisted, so a failed or timed-out run cannot overwrite anything.
- `POST /rosters/{month}/save` takes `{assignments, fingerprint, expected_version|null, replace_existing}`.
  - Under the lock it recomputes the fingerprint: a hash of the worker ids and their row versions, the resolved contract ids, the demand, the roster version, `free_from`, and the neighbor rosters' versions.
    - A mismatch returns 409 `STALE_PREVIEW`. This includes the case where a shift started between generate and save.
  - Assignments in started shifts must equal the stored ones; otherwise it returns 422 `LOCKED_SHIFT`.
  - Replacing an existing roster needs `replace_existing` and the matching version. The UI first shows "replaces N assignments, last edited by X at T".
  - It rejects new or worsened hard violations with 422 (the gate of §4.5, so existing violations in locked shifts do not block). It saves as DRAFT; replacing an approved roster revokes its approval (`REGENERATE`).
- `POST /rosters/{month}/assignments`, `DELETE …/assignments/{id}`, `POST …/assignments/{id}/move`.
  - Every one takes `expected_version` and `acknowledge_approved_edit`.
  - Every one is checked under P10, including adjacency against neighbor months.
  - A move runs in one transaction: remove plus add, checked together. On failure nothing changes.
- `GET /rosters/{month}/suggestions?date=&shift=&role=` returns candidates. An apply is just the add endpoint, revalidated.
- `POST /rosters/{month}/approve` (MANAGER) takes `{expected_version, acknowledge_warnings, reason}`.
- `GET /meta` returns shifts, roles and demand.

**Suggestions** (`rosters/suggestions.py`, pure, takes a Problem plus assignments):
- A candidate is an active, contracted worker with the right role. Adding them must leave `worsened(before, after)` empty, which includes adjacency.
- Ranked by min-hour deficit (descending), then assigned hours (ascending), then name.
- Each candidate comes with a reason list, e.g. "Screener · available Tue B · 96/160 h (64 h below minimum) · 1 shift that day".
- There are no swap chains, no solver calls, and no cost-based ranking.

## 7. Frontend screens
- **Login.**
- **Workers:** list with filters; create/edit form with inline 422 errors; delete, falling back to a "deactivate" offer on 409. A role/status change shows a simple confirmation (detailed preview deferred, P7).
- **Worker detail:** contract version timeline, the contract resolved for the selected month, and a new-version form, then an impact preview, then confirm.
- **Import:** upload, then a preview grouped as New, Changed, Unchanged and Invalid, showing diffs, effective month and affected rosters. A red banner appears if an approved roster would be invalidated. Per-employee approve/skip, confirm, result summary; a stale preview offers "reload preview".
- **Export:** month picker.
- **Roster:**
  - Month picker; status badge (none, draft, approved, history).
  - Generate (spinner, 429 message), then a preview showing the solver outcome in plain language, gaps, shortfalls and estimated costs, then "Save as draft" (with a replace confirmation).
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
Commits should be small and coherent. ★ marks a review checkpoint. The first milestone is a thin end-to-end vertical slice. The plan then expands to the full submission: every mandatory requirement plus the two selected additional features (D7).

| # | Task | Owns | Context | Acceptance / tests |
|---|---|---|---|---|
| T0 | Skeleton and shared contracts | compose, Dockerfiles, `app/main,config,db,errors`, `scheduling/types.py` (Assignment with role, Violation with key/magnitude, Problem, results; frozen), `app/api_schemas/` for the slice endpoints, OpenAPI export plus TS type generation, frontend scaffold | §2, §4.2, §4.5, §4.6, §6 | A clean `docker compose up` gives a healthy `/api/health` and serves the frontend. The error-shape test passes. The OpenAPI file is committed and the generated TS types compile |
| T1 | Scheduling engine | `app/scheduling/`, `tests/scheduling/`, `bench/` | §4 | All tests in §4.9 pass; the benchmark table (§4.8) is produced from the actual model |
| T2 | DB schema, auth and seed | `alembic/`, `app/*/models.py`, `app/auth/`, seed (users plus sample workers/contracts) | §3, P12 | Migration from empty works. The immutability trigger rejects UPDATE/DELETE. Constraint tests cover the ID regex, min≤max and unique month. Login/me/logout work; `require_role` returns 403. The seed is idempotent |
| T3 | Roster slice backend | `app/contracts/` resolution (read path), `app/rosters/{problem_builder,evaluation,generation,save,costs}.py`, `approval.revoke` | §3, §4.2, §4.5, §4.6, §6 rosters, P3, P4, P15 | Resolution: past, current and future months, same-month supersede, no contract. Problem builder: inactive, no contract, `free_from` from a frozen clock (before midnight, mid-shift, exactly at a shift start), fixed from stored started shifts, neighbor-month assignments. Generate returns each outcome type, and a failure never persists. Save: fingerprint mismatch gives 409, including a shift that started between generate and save; a changed started shift gives 422 `LOCKED_SHIFT`; replace needs the flag and version; new hard violations give 422, while existing ones in locked shifts do not. Costs: per shift/worker/month, missing contract counted as unknown, `Decimal` rounding. The busy guard returns 429 |
| T4 | Frontend slice | `frontend/src/{api,auth,layout,errors}`, `frontend/src/features/roster` (read, generate, save) | §6 contract, §7 | Generated types compile. Login and the 401 redirect work. The error mapper has a unit test. Manual walkthrough on seeded data: pick a month → generate → grid shows assignments, gaps, shortfalls and costs → save as draft |
| ★M1 | Vertical slice works end to end on a clean `docker compose up` | | | |
| T5 | Workers, contract versions and change-set service (backend and UI) | `app/workers/`, `app/contracts/` (write path), `app/changes/`, `frontend/src/features/workers` | §6, P1, P2, P5, P6, P7 | Israeli-ID checksum valid/invalid cases. CRUD and the 409 on in-use delete. A version-conflict test. Contract change impact lists the affected rosters. Apply keeps assignments, sends invalid approved rosters to draft (`CONTRACT_CHANGE`) and keeps the revoked approval row. A role/status change does the same with `WORKER_CHANGE`. Stale base gives 409 with nothing applied |
| T6 | CSV import/export and sample data (backend and UI) | `app/csvio/`, `sample-data/`, `frontend/src/features/imports` | §6 CSV, P8, P9, P13, P14 | Partial success: invalid rows do not block valid ones. Duplicate-in-file handling. Repeated confirm gives 409. Stale gives 409. A confirmed import that invalidates an approved roster sends it to draft with `CONTRACT_CHANGE` and the import id. Round trip: an unmodified export gives all UNCHANGED. Sample CSV of about 23 workers (9 GG, 9 SCR, 5 SUP) covers a full month under the adjacency rule; the shortage file creates supervisor gaps |
| T7 | Manual edits and suggestions (backend and UI) | `app/rosters/{edits,suggestions}.py`, roster edit UI | P10, §6 | Add/remove/move valid cases. A failed move leaves the original intact. Rejected edits: a new violation, and a worsened one (same key, higher magnitude). Adjacency is rejected within a day, across days, and across a month boundary against the neighbor roster. Removal is allowed on an invalid roster. Editing an approved roster needs the acknowledgement and goes to draft with history kept. Suggestions: eligibility (including adjacency), ranking, reasons, and an apply that is revalidated |
| T8 | Approval (backend and UI) | `app/rosters/approval.py`, approval panel | P11, P12 | A planner gets 403 and a manager succeeds. Hard violations give 422. Warnings without an acknowledgement and reason give 422. Approver and time are recorded. Version conflict gives 409 |
| ★M2 | Full submission feature-complete | | | |
| T9 | End-to-end and README | `README.md`, `tests/e2e/` (httpx against the running stack) | everything | Clean database, compose up, scripted flows pass. README covers architecture, schema, indexes, setup, CSV format, feature value, assumptions, trade-offs and limitations. It also covers the scheduling design, including the weight derivation, the timeout limitations and the benchmark results. The adjacency rule is described as a product decision, and costs as estimates |
| ★M3 | Final | | | |

Backend tests run with pytest against a Postgres test database in compose, with each test rolled back.

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
- Each session edits only the modules it owns. Changes to shared files (`models`, `errors`, `scheduling/types.py`, `api_schemas`, OpenAPI) go through the main session. A session's new endpoints are added to the contract before it starts on them.

## 10. Scope priorities
- **P0, first (vertical slice, M1):** compose startup with seeded data, login, month picker, generate, grid with assignments, gaps, shortfalls and costs, save draft.
- **P0 (must ship, M2):**
  - every mandatory assignment requirement
  - the two selected additional features (D7)
  - workers CRUD
  - immutable versions and resolution
  - CSV preview/confirm, partial success, export round trip
  - engine (§4), including adjacency, fixed assignments and the benchmark
  - add/remove/move with the repair rule (keys and magnitudes)
  - approval invalidation on contract and worker changes, including via CSV
  - suggestions
  - auth and approval
  - estimated costs
  - README and sample data
  - the focused backend tests listed above
- **P1:** detailed impact preview for worker role/status edits, Hypothesis property-based engine tests, frontend unit tests beyond the error mapper, full end-to-end script.
- **P2 (cut first):** drag and drop, Playwright, rich history views, preview expiry.

## 11. Engine/application integration (resolved)
- **C1 Slot role on assignments:** adopted. `Assignment` carries `role` everywhere (engine, API, database), and the validator checks it against the worker's role.
- **C2 Violation keys and magnitudes:** adopted (§4.5). The engine's validation gate, P10 manual edits and suggestions all use `worsened(before, after)`.
- **C3 Workers not in the engine input:** the engine reports them as `UNKNOWN_WORKER`. The application maps that to `NO_CONTRACT_FOR_MONTH`. No engine change.

## 12. Decisions needed from you
- **D1 Repository location.** This plan is saved at `/Users/koz/docs/plans/application.md`. Recommendation: a new git repo `/Users/koz/icts-rostering` with the plan moved to its `docs/plans/application.md`.
- **D2** Confirm or change policies P1–P15. The riskiest are P2 (retroactive changes), P3 (history and locked shifts), P6 (delete), P11 (warning approval) and P12 (permissions).
- **D4** Seeded demo credentials, and whether the README may list them plainly.
- **D5** Sample data size: about 23 workers so a full month is covered at 2/2/1 demand under the adjacency rule (verify with the benchmark generator), plus a separate shortage file.
- **D7** Name the two selected additional features, so §10 and the README can list them explicitly.
