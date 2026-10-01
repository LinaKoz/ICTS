# Login screen redesign

## What changed
- Replaced the split layout (brand panel with large shift-colour blocks + bare form) with one centred glass card over a full-screen backdrop.
- Backdrop: roster-grid dot field (masked to fade out), three blurred glows in the shift colours (slow drift, off under `prefers-reduced-motion`), vignette. Pure CSS, no images.
- Card: logo, one-line tagline, form; a 2px three-shift hairline on the top edge keeps the brand cue. Primary button now uses the accent (`--clearance`) instead of pale ink.
- Light and dark both themed via `--login-*` variables (dark under `prefers-color-scheme: dark`, same as `index.css`).
- Removed `DayHero` and the unused `.login-brand`, `.login-main`, `.login-day*` styles.

## Why
User disliked the old screen (empty space, loud blocks, weak form) and chose an "atmosphere background" direction.

## Files
- `frontend/src/auth/LoginPage.tsx`
- `frontend/src/App.css`

## Tests run
- `npm run typecheck`, `npm run lint`, `npm test` (141 passed).
- Headless Chrome screenshots: dark/light at 1440×900, dark at 390×800.

## Known gaps
- `backdrop-filter` falls back to the translucent card colour where unsupported (still readable).
