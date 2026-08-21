#!/usr/bin/env python3
"""Reject undeclared protocol-v2 capabilities and stale generated catalogs."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_GLOB_V2 = "config/plugin-manifests-v2/*.json"
CATALOG_PATH_V2 = Path("shared/catalogs/plugin-module-catalog.v2.json")
GENERATOR_PATH_V2 = Path("scripts/generate_plugin_protocol_v2.py")

_CONTEXT_METHODS = frozenset({"provide", "require", "on", "dispatch"})
_OPERATION_CONTEXT_TYPE = "OperationContextV2"
_OPERATION_CONTEXT_FACTORIES = frozenset(
    {
        "current_operation_context_v2",
        "pin_agent_turn_operation_v2",
        "pin_operation_context_v2",
        "pin_persisted_generation_operation_v2",
    }
)
_METHOD_DECLARATION = {
    "provide": ("services", "provides", "service"),
    "require": ("services", "requires", "alias"),
    "on": ("events", "handles", "event"),
    "dispatch": ("events", "emits", "event"),
}
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


def check_repository(root: Path) -> tuple[ContractCompletenessIssueV2, ...]:
    """Run the complete manifest/catalog/AST/generated-output gate for one checkout."""
    repository = root.resolve()
    issues: list[ContractCompletenessIssueV2] = []
    modules = _load_manifest_modules(repository, issues)
    _check_catalog(repository, modules, issues)
    for module in modules:
        if "python" in module.targets:
            _check_python_entrypoint(repository, module, issues)
    _check_operation_context_dispatches(repository, modules, issues)
    _check_generated_outputs(repository, issues)
    return tuple(sorted(issues, key=_issue_key))


def _load_manifest_modules(
    root: Path,
    issues: list[ContractCompletenessIssueV2],
) -> tuple[_ManifestModuleV2, ...]:
    modules: list[_ManifestModuleV2] = []
    seen: dict[str, Path] = {}
    manifest_paths = sorted(root.glob(MANIFEST_GLOB_V2))
    if not manifest_paths:
        issues.append(
            ContractCompletenessIssueV2(
                code="manifest_catalog_empty",
                path=MANIFEST_GLOB_V2,
                detail="no protocol-v2 manifests were found",
            )
        )
        return ()

    for path in manifest_paths:
        relative = _relative(path, root)
        payload = _read_json_object(path, "invalid_manifest", issues, root)
        if payload is None:
            continue
        plugin_id = payload.get("plugin_id")
        plugin_version = payload.get("version")
        raw_modules = payload.get("modules")
        if not isinstance(plugin_id, str) or not isinstance(plugin_version, str):
            issues.append(
                ContractCompletenessIssueV2(
                    code="invalid_manifest",
                    path=relative,
                    detail="plugin_id and version must be strings",
                )
            )
            continue
        if not isinstance(raw_modules, list):
            issues.append(
                ContractCompletenessIssueV2(
                    code="invalid_manifest",
                    path=relative,
                    detail="modules must be an array",
                )
            )
            continue
        for index, raw_module in enumerate(raw_modules):
            module = _manifest_module(
                path=path,
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                index=index,
                payload=raw_module,
                issues=issues,
                root=root,
            )
            if module is None:
                continue
            previous = seen.get(module.module_ref)
            if previous is not None:
                issues.append(
                    ContractCompletenessIssueV2(
                        code="duplicate_manifest_module",
                        path=relative,
                        module_ref=module.module_ref,
                        detail=f"module_ref also appears in {_relative(previous, root)}",
                    )
                )
                continue
            seen[module.module_ref] = path
            modules.append(module)
    return tuple(modules)


def _manifest_module(
    *,
    path: Path,
    plugin_id: str,
    plugin_version: str,
    index: int,
    payload: object,
    issues: list[ContractCompletenessIssueV2],
    root: Path,
) -> _ManifestModuleV2 | None:
    relative = _relative(path, root)
    if not isinstance(payload, dict):
        issues.append(
            ContractCompletenessIssueV2(
                code="invalid_manifest",
                path=relative,
                detail=f"modules[{index}] must be an object",
            )
        )
        return None
    raw = cast("dict[str, Any]", payload)
    artifact = raw.get("artifact")
    required_strings = {
        "module_ref": raw.get("module_ref"),
        "entrypoint": raw.get("entrypoint"),
        "contract_digest": raw.get("contract_digest"),
    }
    invalid = [name for name, value in required_strings.items() if not isinstance(value, str)]
    if invalid or not isinstance(artifact, dict) or not isinstance(artifact.get("digest"), str):
        issues.append(
            ContractCompletenessIssueV2(
                code="invalid_manifest",
                path=relative,
                detail=f"modules[{index}] has invalid required fields: {', '.join(invalid)}",
            )
        )
        return None
    targets = raw.get("targets")
    contract = raw.get("contract")
    if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
        issues.append(
            ContractCompletenessIssueV2(
                code="invalid_manifest",
                path=relative,
                detail=f"modules[{index}].targets must be a string array",
            )
        )
        return None
    if not isinstance(contract, dict):
        issues.append(
            ContractCompletenessIssueV2(
                code="invalid_manifest",
                path=relative,
                detail=f"modules[{index}].contract must be an object",
            )
        )
        return None
    return _ManifestModuleV2(
        path=path,
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        module_ref=cast("str", required_strings["module_ref"]),
        entrypoint=cast("str", required_strings["entrypoint"]),
        artifact_digest=cast("str", artifact["digest"]),
        targets=tuple(cast("list[str]", targets)),
        contract=cast("dict[str, Any]", contract),
        contract_digest=cast("str", required_strings["contract_digest"]),
    )


def _check_catalog(
    root: Path,
    modules: Sequence[_ManifestModuleV2],
    issues: list[ContractCompletenessIssueV2],
) -> None:
    path = root / CATALOG_PATH_V2
    payload = _read_json_object(path, "generated_catalog_missing", issues, root)
    if payload is None:
        return
    raw_modules = payload.get("modules")
    if not isinstance(raw_modules, list):
        issues.append(
            ContractCompletenessIssueV2(
                code="invalid_generated_catalog",
                path=str(CATALOG_PATH_V2),
                detail="modules must be an array",
            )
        )
        return

    catalog = _catalog_rows(raw_modules, issues)
    manifest_refs = {module.module_ref for module in modules}
    for module in modules:
        _check_catalog_module(root, module, catalog.get(module.module_ref), issues)
    for module_ref in sorted(set(catalog) - manifest_refs):
        issues.append(
            ContractCompletenessIssueV2(
                code="stale_catalog_module",
                path=str(CATALOG_PATH_V2),
                module_ref=module_ref,
                detail="generated catalog module has no manifest declaration",
            )
        )


def _catalog_rows(
    raw_modules: Sequence[object],
    issues: list[ContractCompletenessIssueV2],
) -> Mapping[str, Mapping[str, Any]]:
    catalog: dict[str, Mapping[str, Any]] = {}
    for index, raw_module in enumerate(raw_modules):
        if not isinstance(raw_module, dict) or not isinstance(raw_module.get("module_ref"), str):
            issues.append(
                ContractCompletenessIssueV2(
                    code="invalid_generated_catalog",
                    path=str(CATALOG_PATH_V2),
                    detail=f"modules[{index}] must contain a string module_ref",
                )
            )
            continue
        module_ref = cast("str", raw_module["module_ref"])
        if module_ref in catalog:
            issues.append(
                ContractCompletenessIssueV2(
                    code="duplicate_catalog_module",
                    path=str(CATALOG_PATH_V2),
                    module_ref=module_ref,
                    detail="generated catalog contains module_ref more than once",
                )
            )
            continue
        catalog[module_ref] = cast("dict[str, Any]", raw_module)
    return catalog


def _check_catalog_module(
    root: Path,
    module: _ManifestModuleV2,
    row: Mapping[str, Any] | None,
    issues: list[ContractCompletenessIssueV2],
) -> None:
    if row is None:
        for target in module.targets:
            issues.append(
                ContractCompletenessIssueV2(
                    code="missing_target_catalog",
                    path=_relative(module.path, root),
                    module_ref=module.module_ref,
                    detail=f"target {target} is absent from the generated catalog",
                )
            )
        return
    catalog_targets = row.get("targets")
    target_set = set(catalog_targets) if isinstance(catalog_targets, list) else set()
    for target in module.targets:
        if target not in target_set:
            issues.append(
                ContractCompletenessIssueV2(
                    code="missing_target_catalog",
                    path=_relative(module.path, root),
                    module_ref=module.module_ref,
                    detail=f"target {target} is absent from the generated catalog row",
                )
            )
    expected = {
        "plugin_id": module.plugin_id,
        "plugin_version": module.plugin_version,
        "entrypoint": module.entrypoint,
        "artifact_digest": module.artifact_digest,
        "contract": module.contract,
        "contract_digest": module.contract_digest,
    }
    mismatches = [name for name, value in expected.items() if row.get(name) != value]
    if mismatches:
        issues.append(
            ContractCompletenessIssueV2(
                code="catalog_module_mismatch",
                path=str(CATALOG_PATH_V2),
                module_ref=module.module_ref,
                detail=f"generated row differs in: {', '.join(sorted(mismatches))}",
            )
        )


def _check_python_entrypoint(
    root: Path,
    module: _ManifestModuleV2,
    issues: list[ContractCompletenessIssueV2],
) -> None:
    module_name, separator, symbol_name = module.entrypoint.partition(":")
    if not separator or not module_name or not symbol_name:
        issues.append(
            ContractCompletenessIssueV2(
                code="invalid_python_entrypoint",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail=f"entrypoint is not module:symbol: {module.entrypoint}",
            )
        )
        return
    source_path = _python_module_path(root, module_name)
    if source_path is None:
        issues.append(
            ContractCompletenessIssueV2(
                code="python_entrypoint_missing",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail=f"source module does not exist: {module_name}",
            )
        )
        return
    relative_source = _relative(source_path, root)
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code="python_entrypoint_invalid",
                path=relative_source,
                module_ref=module.module_ref,
                detail=str(exc),
            )
        )
        return
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    entrypoint = functions.get(symbol_name)
    if entrypoint is None:
        issues.append(
            ContractCompletenessIssueV2(
                code="python_entrypoint_missing",
                path=relative_source,
                module_ref=module.module_ref,
                detail=f"function is not defined: {symbol_name}",
            )
        )
        return

    declarations = _contract_declarations(module, relative_source, issues)
    nodes = _entrypoint_nodes(entrypoint, functions, module, relative_source, issues)
    constants = _static_string_constants(root, module_name, tree)
    for node in nodes:
        _check_context_calls(node, declarations, constants, module, relative_source, issues)


def _entrypoint_nodes(
    entrypoint: ast.FunctionDef | ast.AsyncFunctionDef,
    functions: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
    module: _ManifestModuleV2,
    source_path: str,
    issues: list[ContractCompletenessIssueV2],
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    result = [entrypoint]
    nested_names = {
        node.name
        for node in ast.walk(entrypoint)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in ast.walk(entrypoint):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "PluginDefinitionV2":
            continue
        keyword = next((item for item in node.keywords if item.arg == "apply"), None)
        if keyword is None:
            issues.append(
                ContractCompletenessIssueV2(
                    code="unclassified_entrypoint_apply",
                    path=source_path,
                    line=node.lineno,
                    module_ref=module.module_ref,
                    detail="PluginDefinitionV2 apply is not explicit",
                )
            )
            continue
        if isinstance(keyword.value, ast.Name):
            if keyword.value.id in nested_names:
                continue
            referenced = functions.get(keyword.value.id)
            if referenced is not None:
                result.append(referenced)
                continue
        issues.append(
            ContractCompletenessIssueV2(
                code="unclassified_entrypoint_apply",
                path=source_path,
                line=keyword.value.lineno,
                module_ref=module.module_ref,
                detail="PluginDefinitionV2 apply target is not a local static function",
            )
        )
    reachable = list(dict.fromkeys(result))
    seen = set(reachable)
    for current in reachable:
        for node in ast.walk(current):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            referenced = functions.get(node.func.id)
            if referenced is None or referenced in seen:
                continue
            seen.add(referenced)
            reachable.append(referenced)
    return tuple(reachable)


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
                            detail="OperationContextV2.dispatch requires a literal event declaration key",
                        )
                    )
                elif event not in emitted_events:
                    issues.append(
                        ContractCompletenessIssueV2(
                            code="undeclared_operation_event",
                            path=relative,
                            line=call.lineno,
                            detail=f"OperationContextV2.dispatch {event} has no module emitter contract",
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


def _contract_declarations(
    module: _ManifestModuleV2,
    source_path: str,
    issues: list[ContractCompletenessIssueV2],
) -> Mapping[str, frozenset[str]]:
    result: dict[str, frozenset[str]] = {}
    try:
        for method, (section, collection, field) in _METHOD_DECLARATION.items():
            section_value = module.contract[section]
            if not isinstance(section_value, Mapping):
                raise TypeError(f"contract.{section} must be an object")
            rows = section_value[collection]
            if not isinstance(rows, list):
                raise TypeError(f"contract.{section}.{collection} must be an array")
            values: list[str] = []
            for row in rows:
                if not isinstance(row, Mapping) or not isinstance(row.get(field), str):
                    raise TypeError(f"contract.{section}.{collection} rows require string {field}")
                values.append(cast("str", row[field]))
            result[method] = frozenset(values)
    except (KeyError, TypeError) as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code="invalid_module_contract",
                path=source_path,
                module_ref=module.module_ref,
                detail=str(exc),
            )
        )
        return {method: frozenset() for method in _CONTEXT_METHODS}
    return result


def _check_context_calls(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    declarations: Mapping[str, frozenset[str]],
    constants: Mapping[str, str],
    module: _ManifestModuleV2,
    source_path: str,
    issues: list[ContractCompletenessIssueV2],
) -> None:
    context_names = _context_parameter_names(node)
    if not context_names:
        return
    parents = {child: parent for parent in ast.walk(node) for child in ast.iter_child_nodes(parent)}
    for item in ast.walk(node):
        if isinstance(item, ast.Attribute) and _is_context_method(item, context_names):
            parent = parents.get(item)
            if not isinstance(parent, ast.Call) or parent.func is not item:
                issues.append(
                    ContractCompletenessIssueV2(
                        code="unclassified_context_call",
                        path=source_path,
                        line=item.lineno,
                        module_ref=module.module_ref,
                        detail=f"context.{item.attr} is not called directly",
                    )
                )
        if not isinstance(item, ast.Call):
            continue
        dynamic_method = _dynamic_context_method(item.func, context_names)
        if dynamic_method is not None:
            issues.append(
                ContractCompletenessIssueV2(
                    code="unclassified_context_call",
                    path=source_path,
                    line=item.lineno,
                    module_ref=module.module_ref,
                    detail=dynamic_method,
                )
            )
            continue
        if not isinstance(item.func, ast.Attribute) or not _is_context_method(
            item.func, context_names
        ):
            continue
        method = item.func.attr
        value = _literal_call_key(item, method, constants)
        if value is None:
            issues.append(
                ContractCompletenessIssueV2(
                    code="unclassified_context_call",
                    path=source_path,
                    line=item.lineno,
                    module_ref=module.module_ref,
                    detail=f"context.{method} requires a literal string declaration key",
                )
            )
            continue
        if value not in declarations[method]:
            issues.append(
                ContractCompletenessIssueV2(
                    code="undeclared_context_call",
                    path=source_path,
                    line=item.lineno,
                    module_ref=module.module_ref,
                    detail=f"context.{method} {value} is absent from the module contract",
                )
            )


def _context_parameter_names(node: ast.AST) -> frozenset[str]:
    result: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments: Iterable[ast.arg] = (
            *item.args.posonlyargs,
            *item.args.args,
            *item.args.kwonlyargs,
        )
        for argument in arguments:
            if _annotation_name(argument.annotation) == "ContextV2":
                result.add(argument.arg)
    return frozenset(result)


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


def _is_context_method(attribute: ast.Attribute, context_names: frozenset[str]) -> bool:
    return (
        attribute.attr in _CONTEXT_METHODS
        and isinstance(attribute.value, ast.Name)
        and attribute.value.id in context_names
    )


def _dynamic_context_method(function: ast.expr, context_names: frozenset[str]) -> str | None:
    if not isinstance(function, ast.Call) or not isinstance(function.func, ast.Name):
        return None
    if function.func.id != "getattr" or not function.args:
        return None
    receiver = function.args[0]
    if not isinstance(receiver, ast.Name) or receiver.id not in context_names:
        return None
    return "dynamic getattr call on ContextV2 cannot be classified"


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


def _check_generated_outputs(
    root: Path,
    issues: list[ContractCompletenessIssueV2],
) -> None:
    generator = root / GENERATOR_PATH_V2
    if not generator.is_file():
        issues.append(
            ContractCompletenessIssueV2(
                code="generator_missing",
                path=str(GENERATOR_PATH_V2),
                detail="protocol-v2 generator does not exist",
            )
        )
        return
    try:
        result = subprocess.run(
            [sys.executable, str(generator), "--check"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code="generated_outputs_stale",
                path=str(GENERATOR_PATH_V2),
                detail=str(exc),
            )
        )
        return
    if result.returncode == 0:
        return
    output = "\n".join(item.strip() for item in (result.stderr, result.stdout) if item.strip())
    issues.append(
        ContractCompletenessIssueV2(
            code="generated_outputs_stale",
            path=str(GENERATOR_PATH_V2),
            detail=output[:2000] or f"generator exited with status {result.returncode}",
        )
    )


def _read_json_object(
    path: Path,
    error_code: str,
    issues: list[ContractCompletenessIssueV2],
    root: Path,
) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code=error_code,
                path=_relative(path, root),
                detail=str(exc),
            )
        )
        return None
    if not isinstance(value, dict):
        issues.append(
            ContractCompletenessIssueV2(
                code=error_code,
                path=_relative(path, root),
                detail="document must be an object",
            )
        )
        return None
    return cast("dict[str, Any]", value)


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _issue_key(issue: ContractCompletenessIssueV2) -> tuple[str, int, str, str, str]:
    return (
        issue.path,
        issue.line or 0,
        issue.code,
        issue.module_ref or "",
        issue.detail,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    issues = check_repository(args.root)
    for issue in issues:
        print(issue.render(), file=sys.stderr)
    if issues:
        print(f"plugin contract completeness failed with {len(issues)} issue(s)", file=sys.stderr)
        return 1
    print("plugin contract completeness v2: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
