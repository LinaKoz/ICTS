#!/usr/bin/env python3
"""Builds a compact Markdown context pack for AI/code review sessions.

Usage:
    python3 backend/scripts/context_builder.py --output context.md
    python3 backend/scripts/context_builder.py --include "backend/app/rosters/**/*.py"
    python3 backend/scripts/context_builder.py --graphify-query "How does roster generation work?"
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_INCLUDES = (
    "CLAUDE.md",
    "README.md",
    "docs/**/*.md",
    "backend/app/**/*.py",
    "backend/tests/**/*.py",
    "backend/pyproject.toml",
    "frontend/src/**/*.{ts,tsx,css}",
    "frontend/package.json",
    "frontend/vite.config.ts",
)

DEFAULT_EXCLUDES = (
    ".git/**",
    ".env",
    "**/.venv/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/*.pyc",
    "frontend/node_modules/**",
    "frontend/dist/**",
    "backend/openapi.json",
    "context.md",
)

TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class ContextFile:
    path: Path
    relpath: str
    size: int
    sha256: str
    content: str | None
    omitted_reason: str | None = None


def _repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _run_graphify_query(root: Path, graph: Path, question: str, budget: int) -> str:
    graph_path = graph if graph.is_absolute() else root / graph
    if not graph_path.exists():
        return f"Graphify graph not found at `{graph_path}`. Build it with `graphify extract backend/app --no-cluster --out .`."

    try:
        result = subprocess.run(
            (
                "graphify",
                "query",
                question,
                "--graph",
                str(graph_path),
                "--budget",
                str(budget),
            ),
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        return f"Graphify is not available on PATH: {exc}"

    output = result.stdout.strip()
    if result.returncode != 0:
        return f"Graphify query failed with exit code {result.returncode}:\n{output}"
    return output or "_Graphify returned no output._"


def _read_graphify_report(root: Path, report: Path, max_bytes: int) -> str:
    report_path = report if report.is_absolute() else root / report
    if not report_path.exists():
        return f"Graphify report not found at `{report_path}`."
    data = report_path.read_bytes()
    if len(data) > max_bytes:
        return f"Graphify report at `{report_path}` is larger than {max_bytes} bytes; include a query instead."
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return f"Graphify report at `{report_path}` is not valid UTF-8."


def _brace_expand(pattern: str) -> list[str]:
    start = pattern.find("{")
    end = pattern.find("}", start + 1)
    if start == -1 or end == -1:
        return [pattern]
    prefix = pattern[:start]
    suffix = pattern[end + 1 :]
    return [prefix + part + suffix for part in pattern[start + 1 : end].split(",")]


def _normalize_rel(path: Path) -> str:
    return path.as_posix()


def _is_excluded(relpath: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(relpath, pattern) for pattern in patterns)


def _looks_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def _iter_included_files(root: Path, includes: tuple[str, ...], excludes: tuple[str, ...]) -> list[Path]:
    files: set[Path] = set()
    for pattern in includes:
        for expanded in _brace_expand(pattern):
            for path in root.glob(expanded):
                if not path.is_file():
                    continue
                relpath = _normalize_rel(path.relative_to(root))
                if _is_excluded(relpath, excludes):
                    continue
                files.add(path)
    return sorted(files, key=lambda p: _normalize_rel(p.relative_to(root)))


def _read_context_file(root: Path, path: Path, max_file_bytes: int, remaining_bytes: int) -> ContextFile:
    relpath = _normalize_rel(path.relative_to(root))
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    size = len(data)

    if not _looks_text(path):
        return ContextFile(path, relpath, size, digest, None, "non-text extension")
    if size > max_file_bytes:
        return ContextFile(path, relpath, size, digest, None, f"larger than --max-file-bytes ({max_file_bytes})")
    if size > remaining_bytes:
        return ContextFile(path, relpath, size, digest, None, "beyond --max-total-bytes budget")

    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return ContextFile(path, relpath, size, digest, None, "not valid UTF-8")
    if "\x00" in content:
        return ContextFile(path, relpath, size, digest, None, "contains NUL bytes")
    return ContextFile(path, relpath, size, digest, content)


def _build_tree(files: list[ContextFile]) -> str:
    return "\n".join(f"- {file.relpath} ({file.size} bytes)" for file in files)


def _fence_for(content: str) -> str:
    fence = "```"
    while fence in content:
        fence += "`"
    return fence


def build_context(
    root: Path,
    includes: tuple[str, ...] = DEFAULT_INCLUDES,
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    max_file_bytes: int = 80_000,
    max_total_bytes: int = 450_000,
    tree_only: bool = False,
    graphify_queries: tuple[str, ...] = (),
    graphify_graph: Path = Path("graphify-out/graph.json"),
    graphify_report: Path | None = None,
    graphify_budget: int = 1_200,
) -> str:
    root = root.resolve()
    paths = _iter_included_files(root, includes, excludes)
    files: list[ContextFile] = []
    used_bytes = 0
    for path in paths:
        context_file = _read_context_file(root, path, max_file_bytes, max_total_bytes - used_bytes)
        if context_file.content is not None:
            used_bytes += len(context_file.content.encode("utf-8"))
        files.append(context_file)

    commit = _run_git(root, "rev-parse", "--short", "HEAD") or "unknown"
    status = _run_git(root, "status", "--short") or ""
    dirty = "yes" if status else "no"
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    parts = [
        "# Repository Context",
        "",
        f"- Root: `{root}`",
        f"- Generated: `{generated_at}`",
        f"- Git commit: `{commit}`",
        f"- Dirty worktree: `{dirty}`",
        f"- Files matched: `{len(files)}`",
        f"- Content bytes included: `{used_bytes}`",
        "",
        "## File Tree",
        "",
        _build_tree(files) if files else "_No files matched._",
    ]

    if graphify_queries or graphify_report is not None:
        parts.extend(["", "## Graphify Context"])
        if graphify_report is not None:
            parts.extend(["", "### Report", "", _read_graphify_report(root, graphify_report, max_file_bytes)])
        for question in graphify_queries:
            answer = _run_graphify_query(root, graphify_graph, question, graphify_budget)
            parts.extend(["", f"### Query: {question}", "", "```text", answer, "```"])

    omitted = [file for file in files if file.omitted_reason]
    if omitted:
        parts.extend(
            [
                "",
                "## Omitted Content",
                "",
                "\n".join(f"- {file.relpath}: {file.omitted_reason}" for file in omitted),
            ]
        )

    if not tree_only:
        included = [file for file in files if file.content is not None]
        parts.extend(["", "## File Contents"])
        for file in included:
            fence = _fence_for(file.content or "")
            language = file.path.suffix.lower().lstrip(".")
            parts.extend(
                [
                    "",
                    f"### {file.relpath}",
                    "",
                    f"{fence}{language}",
                    file.content.rstrip(),
                    fence,
                ]
            )

    return "\n".join(parts).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_repo_root_from_script(), help="repository root")
    parser.add_argument("--output", type=Path, default=None, help="write Markdown to this path")
    parser.add_argument("--include", action="append", default=None, help="glob to include; may be repeated")
    parser.add_argument("--exclude", action="append", default=None, help="glob to exclude; may be repeated")
    parser.add_argument("--max-file-bytes", type=int, default=80_000)
    parser.add_argument("--max-total-bytes", type=int, default=450_000)
    parser.add_argument("--tree-only", action="store_true", help="emit metadata and tree without file contents")
    parser.add_argument("--graphify-query", action="append", default=None, help="include a Graphify query result")
    parser.add_argument(
        "--graphify-graph",
        type=Path,
        default=Path("graphify-out/graph.json"),
        help="Graphify graph path",
    )
    parser.add_argument("--graphify-report", type=Path, default=None, help="include a small Graphify Markdown report")
    parser.add_argument("--graphify-budget", type=int, default=1_200, help="token budget passed to graphify query")
    parser.add_argument("--list-defaults", action="store_true", help="print default include/exclude globs and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_defaults:
        print("Default includes:")
        print("\n".join(f"  {pattern}" for pattern in DEFAULT_INCLUDES))
        print("Default excludes:")
        print("\n".join(f"  {pattern}" for pattern in DEFAULT_EXCLUDES))
        return 0

    includes = tuple(args.include) if args.include else DEFAULT_INCLUDES
    excludes = tuple(DEFAULT_EXCLUDES + tuple(args.exclude or ()))
    context = build_context(
        root=args.root,
        includes=includes,
        excludes=excludes,
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
        tree_only=args.tree_only,
        graphify_queries=tuple(args.graphify_query or ()),
        graphify_graph=args.graphify_graph,
        graphify_report=args.graphify_report,
        graphify_budget=args.graphify_budget,
    )

    if args.output:
        output = args.output if args.output.is_absolute() else Path(os.getcwd()) / args.output
        output.write_text(context, encoding="utf-8")
        print(f"wrote {output}")
    else:
        print(context, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
