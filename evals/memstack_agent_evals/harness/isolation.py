"""Isolation checks that keep evals independent from the application."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_IMPORT_ROOTS = {"src", "web", "configuration"}


def find_forbidden_imports(root: Path) -> list[str]:
    """Return forbidden imports found in Python files under root."""
    violations: list[str] = []
    for path in root.rglob("*.py"):
        if any(part.startswith(".") for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = _import_root(node)
            if module in FORBIDDEN_IMPORT_ROOTS:
                violations.append(f"{path}:{getattr(node, 'lineno', 0)} imports {module}")
    return violations


def assert_no_forbidden_imports(root: Path) -> None:
    """Raise if eval code imports application internals."""
    violations = find_forbidden_imports(root)
    if violations:
        joined = "\n".join(violations)
        raise AssertionError(f"Forbidden eval imports found:\n{joined}")


def _import_root(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            return alias.name.split(".", 1)[0]
    if isinstance(node, ast.ImportFrom) and node.module:
        return node.module.split(".", 1)[0]
    return None
