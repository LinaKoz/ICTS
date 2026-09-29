"""§4.9 Independence: the engine imports nothing from sqlalchemy, fastapi,
or any app.* module outside `scheduling`."""
import ast
import pathlib

import app.scheduling as scheduling_pkg

FORBIDDEN_PREFIXES = ("sqlalchemy", "fastapi", "psycopg", "alembic")


def _imported_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_scheduling_engine_has_no_forbidden_imports():
    pkg_dir = pathlib.Path(scheduling_pkg.__file__).parent
    offenders = []
    for path in pkg_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for module in _imported_modules(tree):
            if any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                offenders.append((path.name, module))
            outside_engine = module == "app" or (
                module.startswith("app.")
                and module != "app.scheduling"
                and not module.startswith("app.scheduling.")
            )
            if outside_engine:
                offenders.append((path.name, module))
    assert offenders == []
