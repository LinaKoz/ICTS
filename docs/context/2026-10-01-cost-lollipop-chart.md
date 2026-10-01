# Cost breakdown: lollipop chart + table toggle

## What changed
- "Estimated cost per worker" modal (opened from the side panel's "View cost breakdown") now has:
  - Totals header: backend `monthly_total_ils` and summed hours across **all** workers (plus unknown-cost count note).
  - `Chart | Table` segmented toggle (existing `.seg` style), defaults to Chart; view state is local, no refetch (data is the already-loaded `costs` prop).
  - Horizontal lollipop chart, pure HTML/CSS (no chart library installed; none added). Zero baseline, one shared scale for all rows (computed from every worker, so expanding the list never rescales). Axis "Estimated cost (ILS)", sticky at the bottom of the scroll area.
  - Top 10 by default ("Top 10 by estimated cost"), "Show all N" / "Show top 10" when > 10.
  - Each row is a full-width button (≥40px tall): hover / focus / tap shows name, scheduled hours, exact cost in an `aria-live` readout under the chart; `aria-label` carries the same text, `title` the full name (names ellipsize).
  - Table keeps Worker / Hours / Cost and Total row; now uses the same sorted rows as the chart.
- Sorting: amount desc, unknown (`amount_ils: null`) last, ties by name then worker id.
- Hours formatted with grouping (`3,696`) in header and table total.

## Why
Request for a lollipop visualization alongside the table, reusing backend costs (contract rates vary — never hours × rate).

## Files
- `frontend/src/features/roster/CostBreakdown.tsx` (new: dialog, chart, table)
- `frontend/src/features/roster/costChart.ts` (new: `costRows`, `totalHours`, `costScale`, `ilsWhole`, `formatHours`)
- `frontend/src/features/roster/costChart.test.tsx` (new: 13 tests)
- `frontend/src/features/roster/SidePanel.tsx` (inline modal replaced by `<CostBreakdown>`)
- `frontend/src/App.css` (cost totals, lollipop styles, `.table-scroll.cost-table` height so the dialog never double-scrolls)

## Tests run
- `npm run typecheck`, `npm run lint`, `npm test` (141 passed), `npm run build`.
- Headless Chrome against mock API (`VITE_API_MOCK=1`): dark + light, 1100px and 390px, show all, table, Escape close.

## Known gaps
- Roster page itself overflows horizontally at 390px (402px scroll width) — pre-existing, not the modal.
- Costs are not affected by the calendar FilterBar (unchanged semantics; side panel never was).
- Mock data gives most workers identical costs, so the chart looks flat in demo mode.

## Commit hygiene
- Untracked `.agents/`, `.claude/`, `skills-lock.json` are unrelated — leave out of the commit.
