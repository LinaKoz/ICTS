# Context Note: Fix Panel, Month-Boundary Violations, and Swap Conflicts

Date: 2026-09-30
Status: committed on `feat/roster-calendar`, not pushed

- `829b422 fix(roster): return a structured DUPLICATE_ASSIGNMENT conflict for swaps`
- `d59c236 fix(roster): lazy fix suggestions, deduped boundary violations, neighbour refresh`

## What Changed and Why

### 1. Fix panel loads replacements only for the chosen assignment

Problem: opening Fix mounted one `AssignmentFixes` per assignment in the
violation, and each one fetched `GET /rosters/{month}/assignments/{id}/replacements`.
A `MAX_HOURS` violation lists every assignment the worker has that month, so
one click could send about 20 requests. Each request runs a full `build_problem`.

Now:

- Fix lists the violation's editable assignments (worker, date, shift).
- Replacements load only after the planner picks one. At most one is active,
  and clicking it again collapses it.
- The selection logic lives in the pure helper `replacementTargets` in `edit.ts`.
- Unchanged: removal, the locked-shift filter, and the approved-roster
  acknowledgement checkbox.
- Behaviour change: after a successful edit the panel stays open, with the
  selection and ack cleared. It used to close.
  - A violation that still exists stays listed.
  - If the violation's assignments change, its key changes and it remounts closed.

### 2. Cross-month violations are deduplicated in the calendar

Problem: the backend reports an adjacency pair across a month boundary in both
months' responses (`validate_roster` neighbour logic, `types.py`).
`buildIndex` concatenated them, so the violation showed twice and React got
duplicate keys.

Now:

- `violationKey` moved from `FixPanel.tsx` to `calendarData.ts`.
- The key is the code plus the sorted `worker:date:shift` of each assignment,
  so assignment order doesn't matter.
- `buildIndex` skips a violation whose key it has already seen.
- The same key is used for React list keys in `RosterCalendar.tsx` and `SidePanel.tsx`.

### 3. Neighbouring months refresh after edits

Problem: edits only invalidated the edited month. A boundary change can add or
remove violations in the previous or next month.

Now:

- `invalidateAfterEdit(qc, month)` in `api.ts` invalidates the roster,
  assignment-id and suggestion queries for the month and both neighbours.
  The neighbours come from `adjacentMonths`, which handles year boundaries.
- Add, move, remove, swap and save all use it.
  - Save used to invalidate only `rosterKey`, which left assignment ids stale.
- React Query refetches only active queries; off-screen months are just marked stale.

### 4. Swap double-booking returns a structured conflict

Problem: the swap pre-check raised `422 VALIDATION_ERROR` with no details and
a raw worker id, so the UI showed only "Request failed". Swap was already
atomic and already checked locks on both sides.

Now:

- The pre-check in `swap_assignments` (`edits.py`) raises
  `HardViolationsError` with one `DUPLICATE_ASSIGNMENT` `ViolationOut`.
- The existing `explainEditError` then shows
  "<name> is already assigned to <date> shift <X>."
- The pre-check stays ahead of `_gate`, because the double-booked row would
  hit the unique constraint `uq_roster_assignments_roster_worker_date_shift`.
- This conflict is reachable only when the worker already holds that slot in a
  different role, since worker/date/shift is unique.

## Files Touched

- `backend/app/rosters/edits.py`
- `backend/tests/rosters/test_edits.py`:
  - 3 new tests
  - renamed `test_swap_rejected_when_it_would_break_a_rule`; its old name
    claimed it covered the unacknowledged approved swap, which it did not
- `frontend/src/features/roster/FixPanel.tsx`, `edit.ts`, `calendarData.ts`,
  `api.ts`, `RosterCalendar.tsx`, `SidePanel.tsx`
- `frontend/src/App.css` (`.fix-targets` styles)
- `frontend/src/features/roster/fixes.test.ts` (new)

## Tests Run

- Backend, full suite: **429 passed, 0 skipped**.
  - Command: `cd backend && TEST_DATABASE_URL=postgresql://icts:icts@localhost:55432/icts PYTHONPATH=. .venv/bin/python -m pytest`
  - Needs the `icts-test-pg` container on port 55432.
- New backend tests:
  - swap double-book returns the structured error and changes no rows
  - an approved roster rejects an unacknowledged swap; an acknowledged swap
    revokes the approval (`revoke_cause = EDIT`)
  - a started shift on either side of the swap is rejected as locked
- Frontend: `npx -y vitest@5.0.2 run` gave **106 passed**, including 6 new
  tests in `fixes.test.ts`:
  - no replacements load until an assignment is picked
  - a boundary violation shows once, in either assignment order
  - distinct violations on the same cell are kept
  - `adjacentMonths` crosses December/January correctly
  - invalidation marks the month and both neighbours stale, but not the month after
- Other frontend checks:
  - `oxlint`: clean
  - `vite build`: passes
  - `tsc -b --noEmit`: the only errors are the missing `vitest` types (see limitations)

## Known Limitations / Not Tested

- The UI was not checked in a browser: the Fix picker's look, the panel
  staying open after an edit, and the one-at-a-time loading.
- There are no component tests; the repo has no jsdom or testing-library.
  Coverage comes from the pure helpers, not from rendering.
- E2E tests (`tests/e2e`) were not run.
- `vitest` is missing from `frontend/node_modules`, so `npm test` and
  `npm run build` fail locally until someone runs `npm install`.
- Running backend tests while another session uses the same test DB caused
  random failures (`users_username_key` UniqueViolation, unexpected 401s).
  Rerun once no other pytest is running.

## Commit Hygiene

- The two commits contain only the files listed above.
- Another session was working in the repo at the same time. Its changes were
  kept out of these commits:
  - approval, `errors.py`, `openapi.json`, `types.ts` and `test_approval.py`;
    that session has since committed them
  - seed and Vite proxy changes; also committed separately by that session
- Still dirty or untracked and unrelated to this work (don't mix them in):
  - `.gitignore`
  - `CLAUDE.md`
  - `backend/scripts/context_builder.py`
  - `backend/tests/test_context_builder.py`
  - `docs/context/`, including this note, is uncommitted
