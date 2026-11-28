#!/usr/bin/env python3
# ruff: noqa: C901, PLR0911, PLR0912
"""Guard against unwrapped execute(select(...)) in runtime code paths.

This script scans the main persistence/adapter/service layers and fails if it
finds a ``.execute(...)`` call whose first argument is a SQLAlchemy ``select``
statement (or a variable derived from one) that is not wrapped with
``refresh_select_statement(...)`` / ``self._refresh_statement(...)`` or an
explicit ``execution_options(populate_existing=True)`` call.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class QueryState(str, Enum):
    OTHER = "other"
    SELECT = "select"
    WRAPPED_SELECT = "wrapped_select"


TARGET_ROOTS = (
    Path("src/application/services"),
    Path("src/infrastructure/adapters"),
    Path("src/host"),
    *Path("plugins/business").glob("*/backend"),
)

SELECT_CHAIN_METHODS = {
    "alias",
    "cte",
    "distinct",
    "execution_options",
    "filter",
    "filter_by",
    "group_by",
    "having",
    "join",
    "join_from",
    "limit",
    "offset",
    "options",
    "order_by",
    "outerjoin",
    "outerjoin_from",
    "scalar_subquery",
    "select_from",
    "subquery",
    "where",
}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    snippet: str


def _is_truthy_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _classify_expr(node: ast.AST | None, env: dict[str, QueryState]) -> QueryState:
    if node is None:
        return QueryState.OTHER

    if isinstance(node, ast.Name):
        return env.get(node.id, QueryState.OTHER)

    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == "refresh_select_statement":
                inner = _classify_expr(node.args[0] if node.args else None, env)
                return (
                    QueryState.WRAPPED_SELECT
                    if inner in {QueryState.SELECT, QueryState.WRAPPED_SELECT}
                    else QueryState.OTHER
                )
            if func.id == "select":
                return QueryState.SELECT

        if isinstance(func, ast.Attribute):
            if func.attr == "_refresh_statement":
                inner = _classify_expr(node.args[0] if node.args else None, env)
                return (
                    QueryState.WRAPPED_SELECT
                    if inner in {QueryState.SELECT, QueryState.WRAPPED_SELECT}
                    else QueryState.OTHER
                )

            base_state = _classify_expr(func.value, env)
            if base_state in {QueryState.SELECT, QueryState.WRAPPED_SELECT}:
                if func.attr == "execution_options":
                    for kw in node.keywords:
                        if kw.arg == "populate_existing" and _is_truthy_constant(kw.value):
                            return QueryState.WRAPPED_SELECT
                if func.attr in SELECT_CHAIN_METHODS:
                    return base_state

    if isinstance(node, ast.Attribute):
        return _classify_expr(node.value, env)

    return QueryState.OTHER


def _iter_child_calls(stmt: ast.stmt) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(stmt):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            calls.append(node)
    return calls


def _record_assignments(stmt: ast.stmt, env: dict[str, QueryState]) -> None:
    if isinstance(stmt, ast.Assign):
        state = _classify_expr(stmt.value, env)
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                env[target.id] = state
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        env[stmt.target.id] = _classify_expr(stmt.value, env)
    elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
        env[stmt.target.id] = QueryState.OTHER


def _process_body(
    body: list[ast.stmt],
    *,
    path: Path,
    source: str,
    env: dict[str, QueryState],
    violations: list[Violation],
) -> None:
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _process_body(
                stmt.body,
                path=path,
                source=source,
                env=dict(env),
                violations=violations,
            )
            continue

        if isinstance(stmt, ast.ClassDef):
            _process_body(
                stmt.body,
                path=path,
                source=source,
                env=dict(env),
                violations=violations,
            )
            continue

        for call in _iter_child_calls(stmt):
            func = call.func
            if not isinstance(func, ast.Attribute) or func.attr != "execute" or not call.args:
                continue

            state = _classify_expr(call.args[0], env)
            if state == QueryState.SELECT:
                snippet = ast.get_source_segment(source, call.args[0]) or "<unknown>"
                violations.append(
                    Violation(
                        path=path,
                        line=call.lineno,
                        snippet=snippet.splitlines()[0].strip(),
                    )
                )

        _record_assignments(stmt, env)

        nested_bodies: list[list[ast.stmt]] = []
        if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            nested_bodies.extend([stmt.body, stmt.orelse])
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            nested_bodies.append(stmt.body)
        elif isinstance(stmt, ast.Try):
            nested_bodies.extend([stmt.body, stmt.orelse, stmt.finalbody])
            nested_bodies.extend(handler.body for handler in stmt.handlers)
        elif isinstance(stmt, ast.Match):
            nested_bodies.extend(case.body for case in stmt.cases)

        for nested in nested_bodies:
            _process_body(
                nested,
                path=path,
                source=source,
                env=dict(env),
                violations=violations,
            )


def _scan_file(path: Path) -> list[Violation]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    violations: list[Violation] = []
    _process_body(
        list(tree.body),
        path=path,
        source=source,
        env={},
        violations=violations,
    )
    return violations


def main() -> int:
    violations: list[Violation] = []
    for root in TARGET_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if path.name.endswith("_test.py") or "tests" in path.parts:
                continue
            violations.extend(_scan_file(path))

    if not violations:
        print("refresh_select_statement guard passed")
        return 0

    print("Found unwrapped execute(select(...)) call(s):", file=sys.stderr)
    for violation in violations:
        print(
            f"  {violation.path}:{violation.line}: {violation.snippet}",
            file=sys.stderr,
        )
    print(
        "\nWrap select statements passed to execute(...) with refresh_select_statement(...).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
