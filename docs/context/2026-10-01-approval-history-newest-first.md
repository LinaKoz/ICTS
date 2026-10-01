# Approval history is returned newest first

Date: 2026-10-01
Branch: `feat/roster-calendar`

## What changed and why

The approval history panel listed events oldest first, so the latest approval or
revocation sat at the bottom of a long list. The order is now newest first,
defined once in the query rather than reversed in the UI.

- `load_approval_history` orders by `approved_at DESC, id DESC`.
- `revoke_roster` returned `history[-1]` as the revoked event; now `history[0]`.
- `ApprovalPanel` renders the list as received (no `reverse()`).
- API contract change: `RosterOut.approval_history` is newest first. Docstring,
  `openapi.json` and `types.ts` updated to say so.

Chosen over a client-side `reverse()` so the API has one source of truth and a
future limit/pagination ("last 5") takes the right rows.

## Files touched

`backend/app/rosters/approval.py`, `backend/app/api_schemas/rosters.py`,
`backend/openapi.json`, `frontend/src/api/types.ts`,
`frontend/src/features/roster/ApprovalPanel.tsx`,
tests: `backend/tests/rosters/test_approval.py`,
`backend/tests/workers/test_approval_invalidation.py`.

## Tests and verification

Backend `pytest`: 435 passed. Frontend `vitest`: 125 passed; `tsc`/`oxlint` clean.
Tests that assumed oldest-first (`_open_approval_id`, history-order and
re-approval tests) were updated. Docker `backend` and `frontend` rebuilt; the app
on :8080 runs from the image, so a rebuild is needed to see UI changes there.

## Known gaps

Within one event the order is still "Approved ..." then "Revoked ...". No other
consumer of `approval_history` exists besides the panel.

## Commit hygiene

One commit: backend order, UI, tests, docs.
