"""Static inventory of the builtin FastAPI route surface.

Phase P1 of the full-pluginization roadmap migrates the hardcoded
``app.include_router(...)`` calls in ``main.py`` into builtin ``http_route``
plugin rows with stable ids. This module produces the machine-readable
baseline for that migration: an AST-derived, side-effect-free inventory of
every include and route-registration helper, with a content digest so drift
between the code and the checked-in baseline fails fast.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAIN_PY_PATH = Path("src/infrastructure/adapters/primary/web/main.py")
INVENTORY_PATH = Path("config/plugin-profiles/builtin-routes.v1.json")

__all__ = [
    "INVENTORY_PATH",
    "MAIN_PY_PATH",
    "RouteInventory",
    "RouterEntry",
    "generate_route_inventory",
]


@dataclass(frozen=True)
class RouterEntry:
    """One include call or route-registration helper in registration order."""

    row_id: str
    kind: str  # "include_router" | "helper"
    expression: str
    module: str | None
    prefix: str | None
    line: int

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "row_id": self.row_id,
            "kind": self.kind,
            "expression": self.expression,
            "line": self.line,
        }
        if self.module is not None:
            payload["module"] = self.module
        if self.prefix is not None:
            payload["prefix"] = self.prefix
        return payload


@dataclass(frozen=True)
class RouteInventory:
    """Deterministic builtin-route baseline with a content digest."""

    source: str
    entries: tuple[RouterEntry, ...]
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        canonical = json.dumps(
            [entry.to_payload() for entry in self.entries],
            sort_keys=True,
            separators=(",", ":"),
        )
        object.__setattr__(
            self,
            "digest",
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the checked-in baseline representation."""
        return {
            "schemaVersion": 1,
            "source": self.source,
            "digest": self.digest,
            "entries": [entry.to_payload() for entry in self.entries],
        }


def generate_route_inventory(main_py_path: Path = MAIN_PY_PATH) -> RouteInventory:
    """Parse the FastAPI entrypoint and inventory its route registrations."""
    tree = ast.parse(main_py_path.read_text(encoding="utf-8"))
    imports = _collect_imports(tree)
    entries: list[RouterEntry] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        entry = _classify_call(node, imports)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda entry: entry.line)
    return RouteInventory(
        source=str(main_py_path),
        entries=_dedupe_row_ids(entries),
    )


def _dedupe_row_ids(entries: list[RouterEntry]) -> tuple[RouterEntry, ...]:
    """Keep intentionally repeated mounts addressable with ordinal suffixes."""
    seen: dict[str, int] = {}
    deduped: list[RouterEntry] = []
    for entry in entries:
        occurrence = seen.get(entry.row_id, 0) + 1
        seen[entry.row_id] = occurrence
        if occurrence == 1:
            deduped.append(entry)
            continue
        deduped.append(
            RouterEntry(
                row_id=f"{entry.row_id}-{occurrence}",
                kind=entry.kind,
                expression=entry.expression,
                module=entry.module,
                prefix=entry.prefix,
                line=entry.line,
            )
        )
    return tuple(deduped)


def _collect_imports(tree: ast.Module) -> dict[str, str]:
    """Map imported names to their module paths, including inline imports."""
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                mapping[name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                mapping[name] = alias.name
    return mapping


def _classify_call(node: ast.Call, imports: dict[str, str]) -> RouterEntry | None:
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "include_router"
        and isinstance(node.args[0], (ast.Attribute, ast.Name, ast.Call))
    ):
        target = node.args[0]
        prefix = _keyword_text(node, "prefix")
        if isinstance(target, ast.Call):
            expression = f"{ast.unparse(target.func)}()"
            base_name = (
                target.func.attr
                if isinstance(target.func, ast.Attribute)
                else target.func.id
                if isinstance(target.func, ast.Name)
                else ""
            )
            owner = None
        else:
            expression = ast.unparse(target)
            base_name = target.attr if isinstance(target, ast.Attribute) else target.id
            owner = (
                target.value.id
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                else None
            )
        module = imports.get(owner) if owner else imports.get(base_name)
        return RouterEntry(
            row_id=_slug(expression),
            kind="include_router",
            expression=expression,
            module=module,
            prefix=prefix,
            line=node.lineno,
        )
    if isinstance(func, ast.Name) and (
        func.id.startswith("register_") or func.id.startswith("install_")
    ):
        if "middleware" in func.id:
            return None
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Name) and first_arg.id == "app":
            return RouterEntry(
                row_id=_slug(func.id),
                kind="helper",
                expression=func.id,
                module=imports.get(func.id),
                prefix=None,
                line=node.lineno,
            )
    return None


def _keyword_text(node: ast.Call, name: str) -> str | None:
    for keyword in node.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return None


def _slug(expression: str) -> str:
    """Derive a stable builtin row id from one registration expression."""
    text = expression.replace("()", "")
    for prefix in ("register_", "install_"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    text = text.replace(".", "_")
    parts = [part for part in text.split("_") if part and part not in {"router", "routes"}]
    return "-".join(parts)
