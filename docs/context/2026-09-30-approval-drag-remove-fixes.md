# Approval revoke race, drag/drop assignment ids, duplicate remove error

Date: 2026-09-30
Branch: `feat/roster-calendar`
Commit: `d8cbac0` (committed, not pushed)

## What changed and why

### 1. Revoke is bound to the approval the manager saw

- Why: approve and revoke do not bump `rosters.row_version`, and `revoke()`
  revokes the newest open approval without an id. Manager A's stale dialog
  (opened on approval #1) could revoke approval #2, created after B revoked
  #1 and re-approved. The version check alone passes, so A's reason would be
  stored on #2.
- Backend: `RevokeRequest.approval_id` is required. `revoke_approval` compares
  it with the open approval under the same `take_scheduling_lock`, after the
  version and `NOT_APPROVED` checks. A mismatch returns
  `409 STALE_APPROVAL` with `details.current_approval_id`.
- Frontend: `ApprovalPanel.tsx` stores `openApprovalId(roster)` when the
  dialog opens (`revokeTarget` state), so a background refetch never swaps in
  a newer id. `mapError` shows "Approval changed" with a reload action.

### 2. Drag/drop assignment ids

- Why: ids come from `GET /rosters/{month}/assignments`, separately from
  `GET /rosters/{month}`, and are joined by (worker, date, shift). A stale id
  list plus a fresh roster could send a move to a row that had moved since,
  and the edit's version check would not notice. A drag with no matching id
  also returned silently.
- Backend: the list endpoint accepts optional `?version=N` and returns
  `409 VERSION_CONFLICT` unless the roster is at N both before and after the
  rows are read. Without `version` it behaves as before.
- Frontend: `useAssignmentIds(month, version, enabled)` is keyed by version
  and returns `{version, assignments}`. On a 409 it invalidates the roster.
  `idsForVersion` ignores lists from another version (placeholder data
  included). `dropIds` reports a missing dragged or swap-target id, and
  `RosterPage` then shows "Assignment data is updating. Please try again."
  and refreshes both queries without retrying the mutation.
- Edit mode is gated on `ids.data !== undefined`, not `isSuccess`. After
  every edit, the old version's list is refetched and gets a 409 until the
  roster refetch re-keys the query; `isSuccess` would briefly leave edit mode.

### 3. Remove error shown once

- Why: `EditPanel` rendered `remove.error` both in the shared area (under the
  move heading "Can't do that: …") and next to the controls.
- Fix: the shared area shows `move.error` only. The removal error renders once,
  titled "Can't remove {name} from {date} shift {shift}", and keeps its
  reload action. `FixPanel` already rendered it once and was not changed.

## Files touched

Backend: `app/api_schemas/approval.py`, `app/errors.py`,
`app/rosters/approval.py`, `app/rosters/edits.py`, `openapi.json`
(regenerated), `tests/rosters/test_approval.py`, `tests/rosters/test_edits.py`.

Frontend: `src/api/types.ts` (regenerated), `src/errors/mapError.ts`,
`src/features/roster/{ApprovalPanel.tsx, EditPanel.tsx, EditPanel.test.tsx
(new), RosterPage.tsx, api.ts, approval.ts, approval.test.ts, edit.ts,
edit.test.ts}`.

## Tests and verification

- Backend pytest (full, isolated DB `icts_claude_2fe2` in `icts-test-pg`,
  dropped afterwards): 430 passed. The other session's
  `tests/test_context_builder.py` was excluded. New regressions:
  `test_stale_revoke_dialog_never_revokes_a_newer_approval` and
  `test_assignment_ids_are_bound_to_the_roster_version_shown`.
- Frontend: `npx vitest run` 115 passed and `npm run lint` is clean.
  `EditPanel.test.tsx` fails on the pre-fix `EditPanel.tsx` and passes after.
- `npm run typecheck` / `npm run build`: the only errors are
  `Cannot find module 'vitest'`. They are pre-existing: `vitest` is not in
  `frontend/node_modules` (it runs via npx). `npx vite build` passes.
- `docker compose up -d --build`: main stack rebuilt. The served bundle on
  :8080 contains the new strings and `assignments?version=`.
- E2E on an isolated stack (`-p t9`, port 18080): 13 passed, 1 failed.
  - Failing test: `test_hard_violation_edit_returns_422_with_the_violation_list`,
    which expects `WRONG_ROLE`.
  - The same failure occurs on `d59c236`, the commit before this fix, so it
    is pre-existing and unrelated.
  - The t9 run needed an override that resets the backend `ports`, because
    `docker-compose.yml` hard-codes `127.0.0.1:8000`.
- Manual API check on the t9 stack:
  - Stale ids return 409.
  - A revoke without `approval_id` returns 422.
  - The A/B race returns `409 STALE_APPROVAL`, and #2 stays active with no
    reason stored.

## Known limitations / not tested

- No browser run of the UI. There is no component-level test of the revoke
  dialog because there is no DOM test env; `EditPanel.test.tsx` uses
  `renderToStaticMarkup` plus `vi.mock('./api')`.
- Clicking an assignment without an id still does nothing and shows no
  message (`RosterPage.tsx`, the `onAssignment` handler). This was out of
  scope.
- The approve endpoint has no approval-id binding; it was out of scope.
- After each edit there is one wasted 409 request for the old version's
  id list. This is expected.

## Commit hygiene

- `d8cbac0` contains only the 18 files above.
- Not part of it: uncommitted context-builder/Graphify work from another
  session. Keep it out of roster fix commits:
  - `.gitignore`
  - `CLAUDE.md`
  - `context-notes.md`
  - `backend/scripts/context_builder.py`
  - `backend/tests/test_context_builder.py`
  - `docs/context/` (including this note)
- Several sessions edited this checkout concurrently. Check `git status`
  before staging, and use a separate `TEST_DATABASE_URL` database when
  another pytest is running against `icts-test-pg`.
