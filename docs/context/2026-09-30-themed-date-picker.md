# Themed date picker replaces the native date input

Date: 2026-09-30
Branch: `feat/roster-calendar`

## What changed and why

The browser's `<input type="date">` popup (light-styled, unthemed, different per browser)
was replaced by `DatePicker` in the roster toolbar ("Go to date") and in the edit
panel's move form ("Date").

- Trigger button with a calendar icon and a short date ("7 Nov 2026").
- Popover matching the generation-settings popover: Monday-first grid (same
  `monthWeeks` as the calendar), selected day filled, today outlined,
  neighbouring-month days dimmed, prev/next month, click the title to jump by
  month/year, Today link.
- Keyboard: arrows move by day/week, PageUp/PageDown by month, Home/End to the
  week's ends, Enter picks, Escape closes and refocuses the trigger. Also closes
  on a click outside.
- `min`/`max` disable days and months outside the range (edit panel: the roster's
  month). The old `max` was `${month}-31`, an invalid date in shorter months; it
  now uses `daysInMonth`.

## Files touched

`frontend/src/features/roster/DatePicker.tsx` (new), `DatePicker.test.tsx` (new),
`calendar.ts` (`dateLabel`, `clampDate`), `CalendarToolbar.tsx`, `EditPanel.tsx`,
`frontend/src/App.css` (`.dp-*` styles; removed `.cal-datepick`).

## Tests and verification

- `npx vitest run`: 119 passed (new: `clampDate`, closed trigger, open Monday-first
  grid with selected day, min/max disabling). `npm run lint` clean; typecheck shows
  only the pre-existing `Cannot find module 'vitest'` errors.
- Rendered the open picker with the built CSS in headless Chrome (dark scheme):
  layout and colours look right. Frontend container rebuilt; bundle contains it.

## Known limitations / not tested

- Keyboard navigation, click-outside and focus handling are not covered by tests
  (no DOM test environment) and were not exercised in a real browser.
- The light colour scheme was not seen (the screenshot machine is in dark mode).
- In the edit panel the popover opens inside the scrolling panel/modal and can
  overlay the Shift field and buttons.
- Month names and weekday letters are English only, like the rest of the UI.

## Commit hygiene

Commit only the files above plus this note. Other sessions' uncommitted
context-builder/Graphify files (`.gitignore`, `CLAUDE.md`, `context-notes.md`,
`backend/scripts/context_builder.py`, `backend/tests/test_context_builder.py`,
other `docs/context/*` notes) are unrelated.
