# Claude Code Instructions

Before starting substantial work:
- Read relevant notes under `docs/context/`.
- Use `python3 backend/scripts/context_builder.py --tree-only` to inspect available context.
- Use focused includes instead of reading the whole repo when possible.
- Use Graphify for relationship questions, impact analysis, and call paths.

Useful commands:
- `python3 backend/scripts/context_builder.py --include "docs/context/*.md"`
- `graphify query "How does roster generation work?" --budget 1200`
- `graphify affected "build_problem()" --depth 1`

At the end of meaningful work:
- Add or update a context note under `docs/context/YYYY-MM-DD-topic.md`.
- Include what changed, why, files touched, tests run, known gaps, and commit hygiene notes.
