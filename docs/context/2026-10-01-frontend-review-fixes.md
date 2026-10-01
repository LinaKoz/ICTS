# Frontend review fixes (2026-10-01)

A React/TypeScript review of `frontend/` found flow-level state bugs. React misuse was not the problem: there were no Rules of Hooks, purity or mutation issues. The fixes below are minimal and keep business rules unchanged.

## What changed and why

1. **Save sends the generation's forbid flag.** `RosterPage` stored only the toggle's current value. The backend fingerprints `forbid_adjacent_shifts` (`problem_builder.compute_fingerprint`), so changing the toggle after generating made Save fail with 409 STALE_PREVIEW ("Data changed"). The offered Reload then threw the proposal away.
   - The flag used for the generation is now kept in `previewForbid`.
   - The body is built by the new pure helper `saveRequest()` in `features/roster/outcome.ts`.
2. **`ApprovalPanel` is keyed by month.** If the next month was already cached (week view across a month boundary), the panel stayed mounted. It then carried the approval reason text and the approve error over to the other month.
3. **Workers list keeps previous data while filters change** (`keepPreviousData` in `useWorkers`). Before, the table was replaced by a skeleton on every keystroke.
4. **Contracts section keeps previous data while the "in force for" month loads** (`useContracts(..., { keepPrevious: true })`).
   - Before, the new-version form unmounted during the load and lost its input.
   - The form is now keyed by `versions.length|base.id`. It re-fills only when the contract it was copied from changes, so the change summary always compares against the same base.
   - `ContractsSection` is keyed by worker id, so placeholder data never shows another worker.
5. **Modal handles Escape on the dialog element, not on `document`.** With two dialogs stacked (shift popup, then edit dialog), Escape now closes only the top one. The dialogs are DOM siblings, so no `stopPropagation` is needed. Leaving it out also keeps the DatePicker's document Escape listener working.
6. **Logout no longer leaves an unhandled rejection** when the request fails.
7. **Worker details conflict "Reload" refetches the worker** instead of `window.location.reload()`. The old reload threw away the roster page state when the details form was opened from the roster dialog.
8. **A 404 on delete shows only "That worker no longer exists"**, not a generic error panel as well.

9. **An identical toast is shown only once while it is visible** (`showToast` in `errors/toastStore.ts`). Before, one network failure hitting several queries on the roster page stacked 2–4 identical toasts.
10. **One shared `currentMonth()` in Asia/Jerusalem** (`features/roster/calendar.ts`). It replaces two copies that used the browser's time zone, in `ContractsSection` and `ImportPage`.
11. **Modal focus trap.** Tab and Shift+Tab wrap inside the dialog, handled in the dialog's own `onKeyDown`, as Escape is.
12. **One set of shift and role names.**
    - Shift names are A Night, B Day and C Evening, as the user confirmed.
    - `SHIFT_INFO` in `roster/names.ts` is the only source; the contract editor's own `SHIFT_CARD` copy was removed. Shift C now reads 16:00–00:00 there too (it showed 24:00 before).
    - Role names come from `roleLabel` in `workers/labels.ts`. It replaces 5 local maps and 2 `toLowerCase().replace('_', ' ')` copies. The `GG`/`SCR`/`SUP` abbreviations in the calendar are a different label and stay.

## Files touched
- Third pass (labels):
  - `roster/names.ts`
  - `roster/RosterCalendar.tsx`
  - `roster/WorkerFocus.tsx`
  - `roster/FilterBar.tsx`
  - `roster/EditPanel.tsx`
  - `roster/edit.ts`
  - `roster/approval.ts`
  - `roster/SidePanel.tsx`
  - `workers/ContractsSection.tsx`
- Second pass:
  - `frontend/src/errors/toastStore.ts`
  - `frontend/src/errors/toastStore.test.ts`
  - `frontend/src/features/roster/calendar.ts`
  - `frontend/src/features/roster/calendar.test.ts`
  - `frontend/src/features/imports/ImportPage.tsx`
  - `frontend/src/components/Modal.tsx`
- First pass:
- `frontend/src/features/roster/RosterPage.tsx`
- `frontend/src/features/roster/outcome.ts`
- `frontend/src/features/roster/outcome.test.ts`
- `frontend/src/features/workers/api.ts`
- `frontend/src/features/workers/ContractsSection.tsx`
- `frontend/src/features/workers/WorkerDetailPage.tsx`
- `frontend/src/features/workers/WorkersPage.tsx`
- `frontend/src/components/Modal.tsx`
- `frontend/src/layout/AppLayout.tsx`

## Tests run
From `frontend/`:
- `npx tsc -b --noEmit`: exit 0.
- `npm run lint`: exit 0.
- `npx vitest run`: 19 files, 146 tests passed. This includes new tests for `saveRequest`, toast de-duplication and `currentMonth` at the month boundary.

## Known gaps
- No browser pass was done. Fixes 2–5, 7 and 11 are verified by code tracing only.
- There are no DOM-interaction tests. Adding jsdom and testing-library would be a new dev dependency and needs a decision.
- Not done (optional items from the review):
  - A note in the Generation settings popover that a toggle change applies to the next generation.
  - `role="gridcell"` on buttons in the month and mini calendars.

## Commit hygiene
Uncommitted. A suggested single commit: `fix(frontend): review fixes for save flag, month-scoped approval state, placeholder data and modal Escape`.
