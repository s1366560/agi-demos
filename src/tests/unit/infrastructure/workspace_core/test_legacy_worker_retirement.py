"""Retirement contracts for platform-owned Workspace recovery workers."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from src.infrastructure.adapters.primary.web import startup

REPO_ROOT = Path(__file__).resolve().parents[5]
LEGACY_MODELS = {
    "WorkspaceMemberModel",
    "WorkspaceModel",
    "WorkspaceTaskModel",
}
LEGACY_REPOSITORY_PREFIX = "sql_workspace_"
RETIRED_MODULES = (
    "src/application/services/task_execution_session_monitor.py",
    "src/application/services/task_execution_session_recovery.py",
    "src/application/services/workspace_autonomy_idle_waker.py",
    "src/infrastructure/agent/tools/workspace_planning_contract.py",
    "src/infrastructure/agent/workspace/goal_runtime/v2_bridge.py",
    "src/infrastructure/agent/workspace_plan/factory.py",
    "src/infrastructure/agent/workspace_plan/outbox_handlers.py",
    "src/infrastructure/agent/workspace_plan/run_controller.py",
)
RETIRED_STARTUP_MODULES = (
    "src/infrastructure/adapters/primary/web/startup/attempt_recovery.py",
    "src/infrastructure/adapters/primary/web/startup/autonomy_waker.py",
    "src/infrastructure/adapters/primary/web/startup/task_execution_session_recovery.py",
    "src/infrastructure/adapters/primary/web/startup/workspace_plan_outbox.py",
)


def _referenced_names(path: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in LEGACY_MODELS
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in LEGACY_MODELS
    }


def test_retired_workspace_workers_do_not_reference_legacy_models() -> None:
    assert {path: _referenced_names(path) for path in RETIRED_MODULES} == {
        path: set() for path in RETIRED_MODULES
    }


def test_retired_agent_plan_runtime_does_not_compose_legacy_repositories() -> None:
    plan_runtime_paths = RETIRED_MODULES[-5:]
    assert {
        path: LEGACY_REPOSITORY_PREFIX in (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in plan_runtime_paths
    } == dict.fromkeys(plan_runtime_paths, False)


def test_retired_agent_plan_runtime_has_no_legacy_sql_authority() -> None:
    plan_runtime_paths = RETIRED_MODULES[-5:]
    forbidden_fragments = (
        "WorkspacePlanOutboxModel",
        "PlanModel",
        "PlanNodeModel",
        "workspace_plan_outbox",
        "workspace_tasks",
        "workspaces",
    )
    assert {
        path: [
            fragment
            for fragment in forbidden_fragments
            if fragment in (REPO_ROOT / path).read_text(encoding="utf-8")
        ]
        for path in plan_runtime_paths
    } == {path: [] for path in plan_runtime_paths}


def test_retired_workspace_worker_startup_modules_are_deleted() -> None:
    assert {path: (REPO_ROOT / path).exists() for path in RETIRED_STARTUP_MODULES} == dict.fromkeys(
        RETIRED_STARTUP_MODULES, False
    )


def test_startup_package_does_not_export_retired_recovery_workers() -> None:
    source = inspect.getsource(startup)
    assert "initialize_blackboard_outbox_dispatcher" not in source
    assert "initialize_attempt_recovery" not in source
    assert "initialize_task_execution_session_recovery" not in source
    assert "shutdown_blackboard_outbox_dispatcher" not in source
    assert "shutdown_attempt_recovery" not in source
    assert "shutdown_task_execution_session_recovery" not in source
    assert "initialize_workspace_plan_outbox_worker" not in source
    assert "shutdown_workspace_plan_outbox_worker" not in source


def test_retired_blackboard_outbox_has_no_static_startup_module() -> None:
    retired_startup = (
        REPO_ROOT / "src/infrastructure/adapters/primary/web/startup/blackboard_outbox.py"
    )
    assert not retired_startup.exists()
