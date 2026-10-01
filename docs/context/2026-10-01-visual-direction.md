# New visual direction for the whole frontend

Date: 2026-10-01
Branch: `feat/roster-calendar`

## What changed and why

The UI ran on leftovers of the Vite template (`#root` 1126px centred with side borders,
56px `h1`, purple `--accent`, `#social`/`.counter` rules) plus patches: hard-coded
`#d33`/`#2a9d5c`/`#d9a400`/`#333`, a separate login blue, gradients in the logo and login,
ALL-CAPS labels. Replaced with one design language built from the subject (airport
security, three shifts a day). No logic, API or functional copy changed; all class names kept.

- **Tokens** (`index.css`, light + dark): apron grey background, white surfaces, ink text,
  steel secondary text, one action blue (`--clearance`). Old names (`--text`, `--accent`,
  `--bg`...) are aliases so feature styles still resolve.
- **Shift colours follow the time of day**: A night indigo, B day ochre, C evening magenta,
  each with an `-ink` variant for text (ochre fails contrast as text).
- **Coverage gaps are hatched**, not amber, so they never read as shift B.
- **Type**: Barlow (road-signage family) for UI, Barlow Semi Condensed for calendar and
  tables; self-hosted via `@fontsource/*` (works offline in Docker). 1.2 scale, tabular nums.
- **Frame**: 88px left rail (icon + label) instead of the top bar; becomes a top bar under 900px.
- **Signature element**: the 24-hour day band (`DayBand`), on week-view shift labels, in the
  logo mark and as the login hero (replaces the gradient panel and roster art).
- Two radius tiers (3px controls, 6px containers); shadows only on popovers/modals/toasts.
  Labels are sentence case. Primary buttons and "on" states are ink-filled.

## Follow-up tweaks (same day, user feedback)

- Week slots: worker names 15px/600, role labels 14px; each slot is a 2-column grid so two
  workers share a row and a long name wraps between first and last name.
- Week shift labels (left column): shift name 1.44rem bold, name and hours 14px/600, column 100px.
- Approval history: 15px/500 body, bold approver, revoked entries in danger red with red edge.
- Worker focus card: total and shift key on the left, wide month grid (64px day cells, large
  shift letters) on the right, larger hours figure underneath; stacks under 900px.
  The card's Clear button moved into the search box as a small X (`.worker-clear`).
- Workers list: 17px/500 rows, bold names, bolder headers, table fills the viewport height.
- Worker page: two columns via a container query (forms left: details, new contract version;
  records right: contract versions, status and role history); one column under 960px of
  container width, so the roster's worker dialog stays stacked. Larger, heavier text throughout.
  Markup: wrappers in `WorkerDetailPage.tsx`, `ContractsSection` section is `display: contents`
  with the versions list wrapped in a `.panel.wd-contracts`.

## Files touched

`frontend/package.json`, `package-lock.json` (fontsource deps), `frontend/index.html` (title),
`frontend/src/main.tsx`, `frontend/src/index.css` (rewritten), `frontend/src/App.css`
(base section rewritten, roster section tokenised, overrides appended),
`frontend/src/components/DayBand.tsx` (new), `components/Logo.tsx`, `layout/AppLayout.tsx`,
`auth/LoginPage.tsx`, `features/roster/RosterCalendar.tsx` (DayBand in shift label),
`features/roster/WorkerFocus.tsx`, `features/roster/RosterPage.tsx`, `features/roster/ApprovalPanel.tsx` (styles only),
`features/workers/WorkersPage.tsx`, `WorkerDetailPage.tsx`, `ContractsSection.tsx`,
this note.

## Tests and verification

- `npx vitest run`: 125 passed. `npm run lint` clean. `npm run build` OK.
- Frontend container rebuilt. Headless Chrome screenshots (CDP script in scratchpad) of
  login, roster week (light/dark), month, mobile 390px, workers, import (dark). Import page
  text hierarchy fixed after review.

## Known gaps

- Day view, edit modal, approval/fix panels, date picker and generation popover were not
  screenshotted; they inherit tokens but may need spacing touch-ups.
- Login was not seen at mobile width (screenshot profile was already signed in).
- `src/assets/hero.png` is unused (it was before too); not deleted.
- App.css still has some legacy rules overridden by the appended block at the end; a later
  pass could fold the overrides into the original rules.

## Commit hygiene

Commit only the files above. `.agents/`, `.claude/`, `skills-lock.json` are untracked and unrelated.
