# Availability / max-hours changes count from the first free shift

## What changed
- `app/rosters/evaluation.py`: new pure `started_shift_rules(problem, violations)`, applied in `evaluate` after the D9(b) override:
  - `UNAVAILABLE` on a started shift (`< free_from`) is dropped.
  - `MAX_HOURS` is reduced to `cap + magnitude - max(cap, worked)` over free assignments only; worked hours above the cap become `HourOverage` (warning).
- `Evaluation.hour_overages`; API `HourOverageOut` on `RosterOut.hour_overages` and `GenerateOutcomeOut.hour_overages`. Generation also filters `preexisting_violations` with the same rule.
- Frontend: `SidePanel` shows a "Worked over maximum" warning section; the locked-slot ⚠ badge and red frame disappear because the violation is gone.
- Spec: D8 amended in `docs/plans/application.md`.

## Why
A worker who reports mid-shift (e.g. Worker 05, Thursday B, 08–16 running now) that a slot no longer works should not get a violation, a revoked approval, or a P2 locked warning for a shift that is already running. Future same-weekday slots stay flagged. Lowering max hours below what was already worked is a warning; the part future shifts can fix stays a hard `MAX_HOURS`.

## Effects
- Change-set preview: such changes yield no `new_violations` / `locked_violations` and do not revoke approval.
- Edits/suggestions/save gates use raw `validate_roster` + `worsened`, unaffected (relative comparison).

## Files
backend: `app/rosters/evaluation.py`, `app/rosters/serialize.py`, `app/rosters/router.py`, `app/rosters/generation.py`, `app/api_schemas/common.py`, `app/api_schemas/rosters.py`, `openapi.json`; tests `tests/workers/test_contract_changes.py`, `tests/rosters/test_approval.py`.
frontend: `src/api/types.ts` (regenerated), `src/api/schemas.ts`, `src/api/mock/mockServer.ts`, `src/features/roster/SidePanel.tsx`, `src/features/roster/RosterPage.tsx`.

## Tests
- Backend full suite: 440 passed.
- Frontend: `tsc -b` clean, vitest 125 passed.

## Known gaps
- Overages are not part of the approval preview / acknowledgement fingerprint (informational only).
- Generation preview does not apply D9(b) (pre-existing gap, unchanged).

## Commit hygiene
Working tree also holds unrelated uncommitted UI work (visual direction, DayBand, etc.); commit this change separately.

---

# Follow-up: readable revocation references in approval history

## What changed
- `ApprovalEventOut.revoke_ref_label` (backend `app/rosters/approval.py::_ref_labels`): `contract_version:{id}` (table-wide row id, misleading as "contract version 92") resolves to "<worker name>, contract v<version_no> from MM/YYYY"; `worker:{id}` resolves to the worker's name; `import:{id}` stays unlabeled.
- Frontend `describeRevocation` prefers `revoke_ref_label`, falls back to `describeRef`.
- Stored `revoke_ref` unchanged (no migration).

## Note on "roster version"
`roster_version` is the roster `row_version` at approval; it bumps on every save/edit/regenerate (not approve/revoke), so gaps between approvals are expected.

## Tests
- Backend 440 passed (label asserts added in `tests/workers/test_approval_invalidation.py`); frontend tsc clean, vitest 125 passed.
