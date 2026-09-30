from __future__ import annotations

from pathlib import Path

from scripts.context_builder import build_context


def test_build_context_includes_matching_files(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    src = tmp_path / "backend" / "app"
    src.mkdir(parents=True)
    (src / "main.py").write_text("print('hello')\n", encoding="utf-8")

    out = build_context(
        tmp_path,
        includes=("README.md", "backend/app/**/*.py"),
        excludes=(),
        max_file_bytes=1_000,
        max_total_bytes=10_000,
    )

    assert "- README.md" in out
    assert "- backend/app/main.py" in out
    assert "### README.md" in out
    assert "# Demo" in out
    assert "print('hello')" in out


def test_build_context_omits_large_files(tmp_path: Path):
    (tmp_path / "large.md").write_text("x" * 20, encoding="utf-8")

    out = build_context(
        tmp_path,
        includes=("large.md",),
        excludes=(),
        max_file_bytes=10,
        max_total_bytes=10_000,
    )

    assert "large.md: larger than --max-file-bytes (10)" in out
    assert "### large.md" not in out


def test_build_context_honors_tree_only(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    out = build_context(
        tmp_path,
        includes=("README.md",),
        excludes=(),
        tree_only=True,
    )

    assert "## File Tree" in out
    assert "## File Contents" not in out


def test_build_context_excludes_matching_files(tmp_path: Path):
    (tmp_path / "keep.md").write_text("keep\n", encoding="utf-8")
    (tmp_path / "skip.md").write_text("skip\n", encoding="utf-8")

    out = build_context(
        tmp_path,
        includes=("*.md",),
        excludes=("skip.md",),
    )

    assert "keep.md" in out
    assert "skip.md" not in out


def test_build_context_graphify_query_reports_missing_graph(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    out = build_context(
        tmp_path,
        includes=("README.md",),
        excludes=(),
        graphify_queries=("How does generation work?",),
    )

    assert "## Graphify Context" in out
    assert "Graphify graph not found" in out
