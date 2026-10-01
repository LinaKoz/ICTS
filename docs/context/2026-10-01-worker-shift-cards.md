# Worker page: shift-card availability and one change bar

## What changed
- `ContractsSection.tsx`: the Mon–Sun × A/B/C checkbox table is replaced by `ShiftCards` (one card per
  shift, seven day toggles with `aria-pressed`, Select all / Clear all). New contract version and Available
  shifts are separate cards; one `newver-bar` under both holds the change summary and "Preview impact"
  (availability is part of the same contract version, so one action, one version). The impact preview
  and Cancel / Confirm and apply sit under the bar.
- `logic.ts`: `setShiftDays`, `contractChangeLines` ("Max hours 192 → 160", "B: Thu, Fri removed"),
  `contractFormChanged` (Preview impact is disabled until something changed; the month alone is no
  change, P5).
- Styles live in `App.css` (committed with the visual-direction commit).

## Tests
- vitest 128 passed; `tsc -b` clean. Not checked visually in a browser by Claude.

## Known gaps
- Card names follow the request (A · Night, C 16:00–24:00); `SHIFT_INFO` in `features/roster/names.ts`
  still says A "Morning" and C "16:00–00:00".
- Between 960 and 1240px container width, Details stretches to the bar's bottom.
