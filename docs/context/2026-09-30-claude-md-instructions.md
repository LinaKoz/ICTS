# Context Note: Project CLAUDE.md Instructions

Date: 2026-09-30
Status: uncommitted

## What Changed

- Added a root `CLAUDE.md` containing the user-supplied session instructions,
  copied verbatim:
  - Before substantial work: read `docs/context/`, inspect context with
    `python3 backend/scripts/context_builder.py --tree-only`, prefer focused
    `--include` globs, and use Graphify for relationship/impact/call-path
    questions.
  - Useful commands: `context_builder.py --include "docs/context/*.md"`,
    `graphify query ... --budget 1200`, `graphify affected ... --depth 1`.
  - After meaningful work: add or update `docs/context/YYYY-MM-DD-topic.md`
    with what changed, why, files touched, tests, gaps, and commit hygiene.

## Why

The repo had no `CLAUDE.md`. Claude Code loads the root `CLAUDE.md` at the
start of every session, so this makes the context-builder and Graphify
workflow the default for future sessions.

## Files Touched

- `CLAUDE.md` (new)
- `docs/context/2026-09-30-claude-md-instructions.md` (this note, new)

## Tests / Commands Run

- None. Documentation-only change, no code touched.

## Known Limitations

- The request was "add this to:" with no target named. Root `CLAUDE.md` was
  assumed. If a different target was intended (global `~/.claude/CLAUDE.md`,
  `AGENTS.md` for Codex), move or copy the content there.
- Codex does not read `CLAUDE.md`. If Codex sessions should follow the same
  workflow, add an `AGENTS.md` with the same content or a pointer to it.
- The `graphify` CLI commands in `CLAUDE.md` were not run here to verify their
  flags.
- `graphify-out/` is gitignored (see the `.gitignore` diff), so graph output
  has to be regenerated locally in each checkout.

## Commit Hygiene

- Commit `CLAUDE.md` and this note together, e.g.
  `docs: add CLAUDE.md with context-builder and Graphify workflow`.
- Keep separate: the other dirty files belong to the context-builder/Graphify
  tooling work and should get their own commit:
  - `.gitignore` (adds `graphify-out/`)
  - `backend/scripts/context_builder.py`
  - `backend/tests/test_context_builder.py`
  - `docs/context/2026-09-30-approval-drag-remove-fixes.md`
- The approval/drag/remove note has been updated to say those fixes are
  committed in `d8cbac0` ("bind revoke to the shown approval,
  version-matched assignment ids, single removal error").
