#!/usr/bin/env python3
"""Reject legacy Workspace model references from production runtime paths."""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALLOWLIST = REPO_ROOT / "docs/architecture/workspace-core-legacy-reference-allowlist.json"
PYTHON_LEGACY_SYMBOLS = frozenset(
    {
        "BlackboardFileModel",
        "BlackboardPostModel",
        "BlackboardReplyModel",
        "CyberGeneModel",
        "CyberObjectiveModel",
        "SqlBlackboardFileRepository",
        "SqlBlackboardRepository",
        "SqlCyberGeneRepository",
        "SqlCyberObjectiveRepository",
        "SqlTopologyRepository",
        "SqlWorkspaceAgentRepository",
        "SqlWorkspaceCollaborationAuthorityRepository",
        "SqlWorkspaceMemberRepository",
        "SqlWorkspaceMessageRepository",
        "SqlWorkspacePipelineRepository",
        "SqlWorkspacePlanBlackboardRepository",
        "SqlWorkspacePlanEventRepository",
        "SqlWorkspacePlanOutboxRepository",
        "SqlWorkspaceRepository",
        "SqlWorkspaceTaskRepository",
        "SqlWorkspaceTaskSessionAttemptRepository",
        "WorkspaceAgentModel",
        "WorkspaceAgentPolicyModel",
        "WorkspaceBlackboardOutboxModel",
        "WorkspaceCollaborationAuthorityModel",
        "WorkspaceCollaborationMutationReceiptModel",
        "WorkspaceDeploymentModel",
        "WorkspaceMemberModel",
        "WorkspaceMessageModel",
        "WorkspaceModel",
        "WorkspacePipelineContractModel",
        "WorkspacePipelineRunModel",
        "WorkspacePipelineStageRunModel",
        "WorkspacePlanBlackboardEntryModel",
        "WorkspacePlanEventModel",
        "WorkspacePlanModel",
        "WorkspacePlanNodeModel",
        "WorkspacePlanOutboxModel",
        "WorkspaceTaskModel",
        "WorkspaceTaskSessionAttemptModel",
        "TopologyEdgeModel",
        "TopologyNodeModel",
        "PlanModel",
        "PlanNodeModel",
    }
)
PYTHON_LEGACY_MODULES = frozenset(
    {
        "sql_blackboard_file_repository",
        "sql_blackboard_repository",
        "sql_cyber_gene_repository",
        "sql_cyber_objective_repository",
        "sql_topology_repository",
        "sql_workspace_agent_repository",
        "sql_workspace_collaboration_authority_repository",
        "sql_workspace_member_repository",
        "sql_workspace_message_repository",
        "sql_workspace_pipeline",
        "sql_workspace_plan_blackboard",
        "sql_workspace_plan_events",
        "sql_workspace_plan_outbox",
        "sql_workspace_repository",
        "sql_workspace_task_repository",
        "sql_workspace_task_session_attempt_repository",
        "workspace_repositories",
    }
)
RUST_SERVER_LEGACY_REFERENCES = frozenset(
    {
        "DevWorkspaceService",
        "PgWorkspaceRepository",
        "SharedWorkspaces",
        "mod workspace_api",
        "workspace_api",
        "workspace_outbox_worker",
    }
)
DESKTOP_LEGACY_REFERENCES = frozenset(
    {
        "desktop_workspace_messages",
        "desktop_workspaces",
    }
)
LEGACY_SYMBOLS = frozenset(
    PYTHON_LEGACY_SYMBOLS
    | PYTHON_LEGACY_MODULES
    | RUST_SERVER_LEGACY_REFERENCES
    | DESKTOP_LEGACY_REFERENCES
)
ALLOWLIST_CATEGORIES = frozenset({"offline_import", "verification", "reverse_export"})
CATEGORY_PATHS = {
    "offline_import": (
        "agi-stack/apps/desktop/sidecar/src/workspace_core_legacy_import.rs",
        "scripts/avernet-bcs/workspace-migrate.py",
        "scripts/migrate_workspaces.py",
        "src/infrastructure/workspace_core/migration/",
    ),
    "verification": (
        "scripts/avernet-bcs/verify-",
        "scripts/workspace-core/verify-",
    ),
    "reverse_export": (
        "scripts/workspace-core/run-migration-rehearsals.py",
        "src/infrastructure/workspace_core/migration/",
    ),
}
PYTHON_OFFLINE_SOURCE_FILES = frozenset(
    {"src/infrastructure/workspace_core/migration/legacy_models.py"}
)
PYTHON_SCAN_ROOTS = ("src", "scripts")
RUST_SCAN_ROOTS = (
    "agi-stack/apps/server/src",
    "agi-stack/apps/desktop/sidecar/src",
)
RUST_TEST_COMPONENTS = frozenset({"tests", "routing_policy_tests"})

Allowlist = dict[str, dict[str, frozenset[str]]]
References = dict[str, frozenset[str]]


def _path_matches_category(file_path: str, category: str) -> bool:
    return any(file_path.startswith(prefix) for prefix in CATEGORY_PATHS[category])


def _normalize_file_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("legacy Workspace exemption has an invalid file path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError(f"legacy Workspace exemption path is not canonical: {value}")
    return value


def _normalize_symbols(value: object, *, file_path: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"legacy Workspace exemption symbols are missing: {file_path}")
    symbols = frozenset(str(symbol) for symbol in value)
    unknown = symbols - LEGACY_SYMBOLS
    if unknown:
        raise ValueError(
            f"legacy Workspace exemption has unknown symbols for {file_path}: {sorted(unknown)}"
        )
    return symbols


def load_allowlist(path: Path) -> Allowlist:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("allowlistVersion") != 2:
        raise ValueError("unsupported legacy Workspace reference allowlist")
    categories = payload.get("categories")
    category_names = (
        frozenset(str(category) for category in categories)
        if isinstance(categories, Mapping)
        else frozenset()
    )
    if not isinstance(categories, Mapping) or category_names != ALLOWLIST_CATEGORIES:
        raise ValueError(
            "legacy Workspace reference allowlist must declare exactly "
            f"{sorted(ALLOWLIST_CATEGORIES)}"
        )

    normalized: Allowlist = {}
    owners: dict[str, str] = {}
    for category in sorted(ALLOWLIST_CATEGORIES):
        files = categories.get(category)
        if not isinstance(files, Mapping):
            raise ValueError(f"legacy Workspace allowlist category is invalid: {category}")
        normalized_files: dict[str, frozenset[str]] = {}
        for raw_file_path, raw_symbols in files.items():
            file_path = _normalize_file_path(raw_file_path)
            if not _path_matches_category(file_path, category):
                raise ValueError(
                    f"legacy Workspace exemption path is invalid for {category}: {file_path}"
                )
            if previous_owner := owners.get(file_path):
                raise ValueError(
                    "legacy Workspace exemption cannot have multiple categories: "
                    f"{file_path} ({previous_owner}, {category})"
                )
            owners[file_path] = category
            normalized_files[file_path] = _normalize_symbols(
                raw_symbols,
                file_path=file_path,
            )
        normalized[category] = normalized_files
    return normalized


def _scan_python_file(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in PYTHON_LEGACY_SYMBOLS:
            symbols.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in PYTHON_LEGACY_SYMBOLS:
            symbols.add(node.attr)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in PYTHON_LEGACY_SYMBOLS:
                symbols.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            symbols.update(
                alias.name for alias in node.names if alias.name in PYTHON_LEGACY_SYMBOLS
            )
            symbols.update(
                part for part in (node.module or "").split(".") if part in PYTHON_LEGACY_MODULES
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                symbols.update(
                    part for part in alias.name.split(".") if part in PYTHON_LEGACY_MODULES
                )
    return frozenset(symbols)


def _production_rust_source(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    # Repository modules place inline unit tests at the end. They remain useful for migration
    # fixtures, but are not part of the compiled production runtime surface guarded here.
    marker = source.find("#[cfg(test)]")
    return source if marker < 0 else source[:marker]


def _scan_rust_file(path: Path, *, desktop: bool) -> frozenset[str]:
    source = _production_rust_source(path)
    forbidden = DESKTOP_LEGACY_REFERENCES if desktop else RUST_SERVER_LEGACY_REFERENCES
    return frozenset(reference for reference in forbidden if reference in source)


def _is_test_path(relative_path: Path) -> bool:
    return bool(RUST_TEST_COMPONENTS & set(relative_path.parts)) or relative_path.name.startswith(
        "test_"
    )


def scan_legacy_references(repo_root: Path = REPO_ROOT) -> References:
    references: References = {}
    for root_name in PYTHON_SCAN_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            relative_path = path.relative_to(repo_root)
            if _is_test_path(relative_path) or "__pycache__" in relative_path.parts:
                continue
            if str(relative_path) in PYTHON_OFFLINE_SOURCE_FILES:
                continue
            symbols = _scan_python_file(path)
            if symbols:
                references[str(relative_path)] = frozenset(symbols)
    for root_name in RUST_SCAN_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        desktop = "apps/desktop/" in root_name
        for path in sorted(root.rglob("*.rs")):
            relative_path = path.relative_to(repo_root)
            if _is_test_path(relative_path):
                continue
            symbols = _scan_rust_file(path, desktop=desktop)
            if symbols:
                references[str(relative_path)] = symbols
    return references


def _flatten_allowlist(allowlist: Allowlist) -> tuple[References, dict[str, str]]:
    references: References = {}
    categories: dict[str, str] = {}
    for category, files in allowlist.items():
        for file_path, symbols in files.items():
            references[file_path] = symbols
            categories[file_path] = category
    return references, categories


def validate_allowlist(actual: References, allowlist: Allowlist) -> None:
    expected, categories = _flatten_allowlist(allowlist)
    runtime = {
        file_path: sorted(symbols - expected.get(file_path, frozenset()))
        for file_path, symbols in actual.items()
        if symbols - expected.get(file_path, frozenset())
    }
    stale = {
        f"{categories[file_path]}:{file_path}": sorted(symbols - actual.get(file_path, frozenset()))
        for file_path, symbols in expected.items()
        if symbols - actual.get(file_path, frozenset())
    }
    if runtime or stale:
        raise ValueError(
            f"legacy Workspace reference gate failed: runtime={runtime}, stale_exemptions={stale}"
        )


def main() -> int:
    allowlist = load_allowlist(DEFAULT_ALLOWLIST)
    validate_allowlist(scan_legacy_references(), allowlist)
    exemption_count = sum(len(files) for files in allowlist.values())
    print(f"Legacy Workspace runtime references are absent ({exemption_count} exemptions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
