# CSV confirm detects rosters that became affected after the preview

Date: 2026-10-01
Branch: `feat/roster-calendar`

## What changed and why

Review finding M1. `confirm_import` checked staleness only against the workers and
rosters stored in the preview's `base`. A roster that gained an assignment of a
changed worker after the preview (and was approved) was not in `base`, so confirm
applied the import and revoked that approval although the preview showed
`invalidates_approved=false`. Reproduced with the new test before the fix (confirm
returned 200 and revoked 2026-10).

- `changes/service.py`: new public `affected_rosters(session, cs, now)`, the same
  roster selection preview/apply use (`_plan_contracts` -> `_min_months` ->
  `_candidate_rosters`). Preview/apply themselves are unchanged.
- `csvio/service.py`: `_stale_reasons` takes the approved rows' change set and adds
  `roster YYYY-MM is now affected` for any currently affected roster not in
  `base["rosters"]`. Result: 409 `STALE_PREVIEW` with a fresh preview, nothing
  applied. Same error shape as before; only a new reason string.

Skipped rows narrow the change set, so the recomputed set is a subset of what the
preview covered; only genuinely new rosters trigger the reason.

## Files touched

`backend/app/changes/service.py`, `backend/app/csvio/service.py`,
`backend/tests/csvio/test_import_flow.py`
(`test_stale_when_a_roster_becomes_affected_after_the_preview`).

## Tests

New test: failed before the fix (200), passes after. `tests/csvio`: 138 passed.
Full backend suite against `icts-test-pg` (:55432): 436 passed.

## Known gaps

Review findings L1-L8 not addressed (out of scope). The contract UI path already
used a fingerprint and was not affected; worker PATCH uses a version check only
(documented, unchanged).

## Commit hygiene

One commit: fix + regression test + this note. `frontend/src/App.css` has an
unrelated uncommitted change; leave it out.
