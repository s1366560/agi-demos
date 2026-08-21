#!/usr/bin/env python3
"""Reject undeclared protocol-v2 capabilities and stale generated catalogs."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.model.plugins.artifact_attestation_v2 import (  # noqa: E402
    artifact_digest_v2,
    python_artifact_path_v2,
    python_artifact_source_v2,
)

if TYPE_CHECKING:
    from scripts.plugin_contract_completeness_support_v2 import (
        ContractCompletenessIssueV2,
        _annotation_name,
        _call_name,
        _check_operation_context_dispatches,
        _literal_call_key,
        _ManifestModuleV2,
        _python_module_path,
        _relative,
        _static_string_constants,
    )
elif __package__:
    from .plugin_contract_completeness_support_v2 import (
        ContractCompletenessIssueV2,
        _annotation_name,
        _call_name,
        _check_operation_context_dispatches,
        _literal_call_key,
        _ManifestModuleV2,
        _python_module_path,
        _relative,
        _static_string_constants,
    )
else:
    from plugin_contract_completeness_support_v2 import (
        ContractCompletenessIssueV2,
        _annotation_name,
        _call_name,
        _check_operation_context_dispatches,
        _literal_call_key,
        _ManifestModuleV2,
        _python_module_path,
        _relative,
        _static_string_constants,
    )

MANIFEST_GLOB_V2 = "config/plugin-manifests-v2/*.json"
CATALOG_PATH_V2 = Path("shared/catalogs/plugin-module-catalog.v2.json")
GENERATOR_PATH_V2 = Path("scripts/generate_plugin_protocol_v2.py")

_CONTEXT_METHODS = frozenset({"provide", "require", "on", "dispatch"})
_STATIC_COMPLETENESS_TARGETS_V2 = frozenset({"python"})
_METHOD_DECLARATION = {
    "provide": ("services", "provides", "service"),
    "require": ("services", "requires", "alias"),
    "on": ("events", "handles", "event"),
    "dispatch": ("events", "emits", "event"),
}


def check_repository(root: Path) -> tuple[ContractCompletenessIssueV2, ...]:
    """Run the complete manifest/catalog/AST/generated-output gate for one checkout."""
    repository = root.resolve()
    issues: list[ContractCompletenessIssueV2] = []
    modules = _load_manifest_modules(repository, issues)
    _check_catalog(repository, modules, issues)
    for module in modules:
        if "python" in module.targets:
            _check_python_entrypoint(repository, module, issues)
        for target in sorted(set(module.targets) - _STATIC_COMPLETENESS_TARGETS_V2):
            issues.append(
                ContractCompletenessIssueV2(
                    code="unsupported_target_completeness",
                    path=_relative(module.path, repository),
                    module_ref=module.module_ref,
                    detail=f"target {target} has no static contract completeness scanner",
                )
            )
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
    if (
        invalid
        or not isinstance(artifact, dict)
        or not isinstance(artifact.get("digest"), str)
        or not isinstance(artifact.get("source"), str)
    ):
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
        artifact_source=cast("str", artifact["source"]),
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
        "artifact_source": module.artifact_source,
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
    attested = _attested_python_entrypoint_source(root, module, issues)
    if attested is None:
        return
    module_name, symbol_name, source_path = attested
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


def _attested_python_entrypoint_source(
    root: Path,
    module: _ManifestModuleV2,
    issues: list[ContractCompletenessIssueV2],
) -> tuple[str, str, Path] | None:
    try:
        expected_path = python_artifact_path_v2(module.entrypoint)
        expected_source = python_artifact_source_v2(module.entrypoint)
    except ValueError as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code="invalid_python_entrypoint",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail=str(exc),
            )
        )
        return None
    if module.artifact_source != expected_source:
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_source_mismatch",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail=f"artifact source must be {expected_source}",
            )
        )
    module_name, symbol_name = module.entrypoint.split(":", maxsplit=1)
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
        return None
    expected_source_path = (root / expected_path).resolve()
    if source_path.resolve() != expected_source_path:
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_source_mismatch",
                path=_relative(module.path, root),
                module_ref=module.module_ref,
                detail="entrypoint module does not resolve to its canonical artifact path",
            )
        )
        return None
    try:
        actual_digest = artifact_digest_v2(source_path.read_bytes())
    except OSError as exc:
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_resolution_failed",
                path=_relative(source_path, root),
                module_ref=module.module_ref,
                detail=str(exc),
            )
        )
        return None
    if actual_digest != module.artifact_digest:
        issues.append(
            ContractCompletenessIssueV2(
                code="artifact_digest_mismatch",
                path=_relative(source_path, root),
                module_ref=module.module_ref,
                detail=f"manifest has {module.artifact_digest}; actual bytes are {actual_digest}",
            )
        )
    return module_name, symbol_name, source_path


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
