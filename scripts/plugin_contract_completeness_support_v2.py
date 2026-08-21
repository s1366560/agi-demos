"""Shared DTOs and Python AST helpers for the protocol-v2 completeness gate."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

_OPERATION_CONTEXT_TYPE = "OperationContextV2"
_OPERATION_CONTEXT_FACTORIES = frozenset(
    {
        "current_operation_context_v2",
        "pin_agent_turn_operation_v2",
        "pin_operation_context_v2",
        "pin_persisted_generation_operation_v2",
    }
)
_METHOD_KEYWORDS = {
    "provide": ("service",),
    "require": ("service_or_alias", "alias"),
    "on": ("event",),
    "dispatch": ("event",),
}


@dataclass(frozen=True, kw_only=True)
class ContractCompletenessIssueV2:
    """One deterministic structural inconsistency found by the gate."""

    code: str
    path: str
    detail: str
    module_ref: str | None = None
    line: int | None = None

    def render(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        owner = "" if self.module_ref is None else f" [{self.module_ref}]"
        return f"{location}: {self.code}{owner}: {self.detail}"


@dataclass(frozen=True, kw_only=True)
class _ManifestModuleV2:
    path: Path
    plugin_id: str
    plugin_version: str
    module_ref: str
    entrypoint: str
    artifact_digest: str
    targets: tuple[str, ...]
    contract: Mapping[str, Any]
    contract_digest: str


def _check_operation_context_dispatches(
    root: Path,
    modules: Sequence[_ManifestModuleV2],
    issues: list[ContractCompletenessIssueV2],
) -> None:
    """Require privileged operation dispatches to reference a public emitter contract."""
    emitted_events = _globally_emitted_events(modules)
    source_root = root / "src"
    if not source_root.is_dir():
        return
    for source_path in sorted(source_root.rglob("*.py")):
        relative_path = source_path.relative_to(root)
        if "tests" in relative_path.parts:
            continue
        relative = str(relative_path)
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        except (OSError, SyntaxError, UnicodeError):
            continue
        module_name = _python_module_name(relative_path)
        constants = _static_string_constants(root, module_name, tree)
        seen_calls: set[tuple[int, int]] = set()
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            context_names = _operation_context_names(function)
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
                location = (call.lineno, call.col_offset)
                if location in seen_calls or not _is_operation_dispatch(call.func, context_names):
                    continue
                seen_calls.add(location)
                event = _literal_call_key(call, "dispatch", constants)
                if event is None:
                    issues.append(
                        ContractCompletenessIssueV2(
                            code="unclassified_operation_event",
                            path=relative,
                            line=call.lineno,
                            detail=(
                                "OperationContextV2.dispatch requires a literal event "
                                "declaration key"
                            ),
                        )
                    )
                elif event not in emitted_events:
                    issues.append(
                        ContractCompletenessIssueV2(
                            code="undeclared_operation_event",
                            path=relative,
                            line=call.lineno,
                            detail=(
                                f"OperationContextV2.dispatch {event} has no module "
                                "emitter contract"
                            ),
                        )
                    )


def _globally_emitted_events(modules: Sequence[_ManifestModuleV2]) -> frozenset[str]:
    emitted: set[str] = set()
    for module in modules:
        events = module.contract.get("events")
        rows = (
            cast("Mapping[str, object]", events).get("emits")
            if isinstance(events, Mapping)
            else None
        )
        if not isinstance(rows, list):
            continue
        for row in cast("list[object]", rows):
            if not isinstance(row, Mapping):
                continue
            event = cast("Mapping[str, object]", row).get("event")
            if isinstance(event, str):
                emitted.add(event)
    return frozenset(emitted)


def _operation_context_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    names = {
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
        if _annotation_name(argument.annotation) == _OPERATION_CONTEXT_TYPE
    }
    for item in ast.walk(node):
        if (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and _annotation_name(item.annotation) == _OPERATION_CONTEXT_TYPE
        ):
            names.add(item.target.id)
        elif isinstance(item, ast.Assign) and _is_operation_context_factory_call(item.value):
            names.update(target.id for target in item.targets if isinstance(target, ast.Name))
        elif isinstance(item, (ast.With, ast.AsyncWith)):
            for with_item in item.items:
                if isinstance(
                    with_item.optional_vars, ast.Name
                ) and _is_operation_context_factory_call(with_item.context_expr):
                    names.add(with_item.optional_vars.id)
    return frozenset(names)


def _is_operation_context_factory_call(value: ast.expr) -> bool:
    return isinstance(value, ast.Call) and _call_name(value.func) in _OPERATION_CONTEXT_FACTORIES


def _is_operation_dispatch(function: ast.expr, context_names: frozenset[str]) -> bool:
    if not isinstance(function, ast.Attribute) or function.attr != "dispatch":
        return False
    receiver = function.value
    return (
        isinstance(receiver, ast.Name) and receiver.id in context_names
    ) or _is_operation_context_factory_call(receiver)


def _annotation_name(annotation: ast.expr | None) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value.rsplit(".", maxsplit=1)[-1]
    return None


def _literal_call_key(
    call: ast.Call,
    method: str,
    constants: Mapping[str, str],
) -> str | None:
    value: ast.expr | None = call.args[0] if call.args else None
    if value is None:
        allowed = _METHOD_KEYWORDS[method]
        value = next((item.value for item in call.keywords if item.arg in allowed), None)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.Name):
        return constants.get(value.id)
    return None


def _static_string_constants(
    root: Path,
    module_name: str,
    tree: ast.Module,
) -> Mapping[str, str]:
    constants = dict(_top_level_string_constants(tree))
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        imported_module = _resolve_import_module(module_name, node)
        if imported_module is None:
            continue
        imported_path = _python_module_path(root, imported_module)
        if imported_path is None:
            continue
        try:
            imported_tree = ast.parse(
                imported_path.read_text(encoding="utf-8"),
                filename=str(imported_path),
            )
        except (OSError, SyntaxError, UnicodeError):
            continue
        imported_constants = _top_level_string_constants(imported_tree)
        for alias in node.names:
            value = imported_constants.get(alias.name)
            if value is not None:
                constants[alias.asname or alias.name] = value
    return constants


def _top_level_string_constants(tree: ast.Module) -> Mapping[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[node.target.id] = node.value.value
    return constants


def _resolve_import_module(module_name: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = module_name.split(".")[:-1]
    parents = node.level - 1
    if parents > len(package):
        return None
    base = package[: len(package) - parents]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base) or None


def _call_name(value: ast.expr) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return None


def _python_module_path(root: Path, module_name: str) -> Path | None:
    relative = Path(*module_name.split("."))
    source = root / relative.with_suffix(".py")
    if source.is_file():
        return source
    package = root / relative / "__init__.py"
    return package if package.is_file() else None


def _python_module_name(relative_path: Path) -> str:
    parts = list(relative_path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        _ = parts.pop()
    return ".".join(parts)


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


__all__ = [
    "ContractCompletenessIssueV2",
    "_ManifestModuleV2",
    "_annotation_name",
    "_call_name",
    "_check_operation_context_dispatches",
    "_literal_call_key",
    "_python_module_path",
    "_relative",
    "_static_string_constants",
]
