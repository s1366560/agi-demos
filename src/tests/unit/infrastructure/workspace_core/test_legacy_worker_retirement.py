"""Retirement contracts for platform-owned Workspace recovery workers."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.adapters.primary.web import startup
from src.infrastructure.adapters.primary.web.startup import (
    attempt_recovery,
    autonomy_waker,
    task_execution_session_recovery as session_recovery,
    workspace_plan_outbox,
)

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
    "src/infrastructure/adapters/primary/web/startup/attempt_recovery.py",
    "src/infrastructure/adapters/primary/web/startup/workspace_plan_outbox.py",
    "src/infrastructure/agent/tools/workspace_planning_contract.py",
    "src/infrastructure/agent/workspace/goal_runtime/v2_bridge.py",
    "src/infrastructure/agent/workspace_plan/factory.py",
    "src/infrastructure/agent/workspace_plan/outbox_handlers.py",
    "src/infrastructure/agent/workspace_plan/run_controller.py",
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


@pytest.mark.unit
async def test_retired_workspace_workers_never_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_ATTEMPT_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_TASK_EXECUTION_SESSION_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("WORKSPACE_PLAN_OUTBOX_ENABLED", "true")

    assert await attempt_recovery.initialize_attempt_recovery() is None
    assert await attempt_recovery.recover_workspace_attempts_once("workspace-1") == 0
    assert await autonomy_waker.initialize_autonomy_idle_waker() is None
    assert (
        await session_recovery.initialize_task_execution_session_recovery(
            container=SimpleNamespace(),  # type: ignore[arg-type]
            redis_client=None,
        )
        is None
    )
    assert await workspace_plan_outbox.initialize_workspace_plan_outbox_worker() is None
    assert await workspace_plan_outbox.shutdown_workspace_plan_outbox_worker() is None


def test_startup_package_does_not_export_retired_recovery_workers() -> None:
    source = inspect.getsource(startup)
    assert "initialize_attempt_recovery" not in source
    assert "initialize_task_execution_session_recovery" not in source
    assert "shutdown_attempt_recovery" not in source
    assert "shutdown_task_execution_session_recovery" not in source
    assert "initialize_workspace_plan_outbox_worker" not in source
    assert "shutdown_workspace_plan_outbox_worker" not in source


def test_retired_workspace_plan_outbox_does_not_import_legacy_worker_graph() -> None:
    source = inspect.getsource(workspace_plan_outbox)
    assert "workspace_plan.outbox_handlers" not in source
    assert "WorkspacePlanOutboxWorker" not in source
