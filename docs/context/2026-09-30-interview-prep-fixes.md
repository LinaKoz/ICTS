# Interview-prep fixes: engine split, CI, small UI fixes

Date: 2026-09-30
Branch: `feat/roster-calendar`, then merged into `main`

## What changed and why

### 1. Engine split out of `scheduling/types.py`

- Why: the whole CP-SAT engine (about 870 lines) lived in a file named
  `types.py`. A reviewer opening "the engine" found data classes first and had
  to scroll to the model.
- Now, all under `backend/app/scheduling/`:
  - `types.py`: enums and dataclasses only, no ortools import.
  - `_helpers.py`: calendar and eligibility helpers.
  - `validation.py`: `validate_problem`, `validate_roster`, `roster_metrics`, `worsened`.
  - `diagnostics.py`: `_slot_deficits`, `diagnose`.
  - `solver.py`: `_run_cp_sat` (test seam), `_coverage_lower_bound`, `solve`.
  - `__init__.py` re-exports the public API. Callers now use `from app.scheduling import ...`.
- Logic moved verbatim. One dead line was removed in `solve`: a first
  `lb = ...` in the UNKNOWN branch that was immediately overwritten.
- Tests that patch the CP-SAT seam now patch `app.scheduling.solver._run_cp_sat`.
- Old unused imports in `tests/scheduling` were removed with `ruff --fix` (F401 only).

### 2. Clicking an assignment with no id

- Why: `onAssignment` in `RosterPage.tsx` silently did nothing when the
  version-bound id list had no row for the clicked chip.
- Now `selectAssignment` shows the same "Assignment data is updating" banner
  as the drag path and refreshes both queries (`idsMissing`, shared).

### 3. Date picker in the edit panel

- Why: the floating popover covered the Shift field and buttons.
- `DatePicker` takes `inline`. The popover then renders in the page flow and
  pushes later fields down. `EditPanel` uses it; the toolbar still floats.

### 4. CI

- `.github/workflows/ci.yml` has three jobs:
  - backend pytest on Python 3.12 with a Postgres 16 service
  - frontend typecheck, lint, test, build on Node 20
  - e2e: `docker compose up -d --build`, wait for `engine: ready`, run `tests/e2e`

### 5. Compose backend port

- Why: `docker-compose.yml` bound the backend to a fixed `127.0.0.1:8000`, so a
  second stack (the README's separate-project e2e recipe, or a clean-clone check)
  failed with "port is already allocated" while the main stack ran.
- Now `${BACKEND_PORT:-8000}`; documented in the README and `.env.example`.

### 6. README

- Engine file layout, `STALE_APPROVAL` in the error list, the revoke
  `approval_id` binding, and why approve needs no approval id.
- Removed the stale "MANUAL revoke stores no reason" limitation. The reason
  was already implemented (`revoke_reason` column, optional `reason` in `RevokeRequest`).

## Checked and not changed

- Approve has no approval-id binding, and does not need one. It takes the
  scheduling lock, requires a DRAFT at `expected_version`, re-evaluates current
  data, and binds acknowledged shortages to a fingerprint. Any content change
  bumps the version.
- `vitest` was already installed after the earlier `npm ci`; `npm test` works.

## Tests run

- Backend full suite on an isolated DB (`icts_fix` in `icts-test-pg`): 435 passed, before and after the split.
- `python -m bench.run small --time-limits 10`: all OPTIMAL, the same numbers as the README table.
- Frontend: typecheck, lint, build clean; vitest 120 passed (new: inline date picker).
- Clean clone of the branch into a temp dir, `FRONTEND_PORT=18080 BACKEND_PORT=18000 docker compose -p icts-fresh up -d --build`: engine ready with no manual step; `tests/e2e`: 14 passed. Stack removed with `down -v`.

## Known gaps

- The CI workflow has not run on GitHub yet; it runs on the first push to `main`.
- No browser run of the inline date picker or the new banner.
- Configurable demand (per shift or weekday) is still a hardcoded constant; left as future work.

## Commit hygiene

- Separate commits: engine split, frontend fixes, CI + README, compose port, this note.
- `feat/roster-calendar` merged into local `main` (merge commit on top of `origin/main`).
- Push NOT done: GitHub rejected it because the `gh` token lacks the `workflow`
  scope needed for `.github/workflows/ci.yml`. After `gh auth refresh -h github.com -s workflow`,
  run `git push origin feat/roster-calendar main`.
- Another session committed `cc41968 docs: summarize original assignment` on this branch during the work; it is included in the merge.

## Follow-up: violations visible on the calendar (same day)

- Why: in week view, a hard violation showed only as a small amber
  "1 rule issue" line under the shift, and the offending worker's chip looked
  normal. The user missed it.
- Now, in red (`--violation`), distinct from amber coverage gaps:
  - the violating worker's chip has a red frame and a ⚠ mark, and its tooltip names the rule
  - the shift cell (week/day) and the day cell (month) get a red left edge
  - "N rule issues" is a red badge
- `violatingWorkers(warnings, date, shift)` in `calendarData.ts` picks the
  chips; test in `violations.test.ts`. Frontend: 121 tests, typecheck, lint, build pass.
- Checked in headless Chrome on the running stack (week of 30 Nov 2026).
- CI: the push to `main` started no run at first. The repo's default branch on
  GitHub is `feat/roster-calendar`, so the workflow now also runs on pushes there
  and has `workflow_dispatch`. First `main` run: backend, frontend and e2e all passed.
- Push worked after `gh auth refresh -h github.com -s workflow`.
