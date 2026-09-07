"""Regression coverage for the Workspace Core-owned cyber-objective surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import BackgroundTasks, HTTPException

from src.application.schemas.workspace_cyber_schemas import (
    CyberObjectiveCreate,
    CyberObjectiveUpdate,
)
from src.application.services.workspace_collaboration_authority import (
    WORKSPACE_COLLABORATION_CONTRACT_VERSION,
    WorkspaceCollaborationActor,
    WorkspaceCollaborationMutationCommand,
)
from src.infrastructure.adapters.primary.web.routers import cyber_objectives
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_mutations import (
    _dispatch_mutation,
)

type _LegacyHandlerCall = Callable[[Any], Awaitable[object]]


def _legacy_handler_calls() -> tuple[_LegacyHandlerCall, ...]:
    common = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
    }
    return (
        lambda current_user: cyber_objectives.create_objective(
            payload=CyberObjectiveCreate(title="Objective"),
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_objectives.list_objectives(
            obj_type=None,
            parent_id=None,
            limit=100,
            offset=0,
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_objectives.get_objective(
            objective_id="objective-1",
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_objectives.update_objective(
            objective_id="objective-1",
            payload=CyberObjectiveUpdate(title="Updated"),
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_objectives.delete_objective(
            objective_id="objective-1",
            current_user=current_user,
            **common,
        ),
        lambda current_user: cyber_objectives.project_objective_to_task(
            objective_id="objective-1",
            body=cyber_objectives.ProjectObjectiveToTaskRequest(),
            current_user=current_user,
            **common,
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize("call", _legacy_handler_calls())
async def test_legacy_cyber_objective_handlers_fail_closed_without_local_runtime(
    call: _LegacyHandlerCall,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await call(cast("Any", SimpleNamespace(id="user-1")))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "code": "WORKSPACE_CORE_UNAVAILABLE",
        "reason": "workspace_core_unavailable",
        "detail": "Workspace Core is unavailable",
    }


@pytest.mark.unit
def test_cyber_objective_contract_module_has_no_static_sql_or_di_fallback() -> None:
    retired_names = {
        "get_container_with_db",
        "get_db",
        "require_workspace_access",
        "_get_workspace_task_service",
        "_get_workspace_task_command_service",
        "_get_workspace_task_event_publisher",
        "_ensure_objective_root_task",
        "_auto_trigger_objective_execution",
    }

    assert retired_names.isdisjoint(vars(cyber_objectives))


@pytest.mark.unit
async def test_collaboration_dispatcher_does_not_execute_local_goal_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def legacy_goal_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("collaboration dispatcher touched the retired goal handler")

    monkeypatch.setattr(cyber_objectives, "create_objective", legacy_goal_trap)
    actor = WorkspaceCollaborationActor(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
    )
    command = WorkspaceCollaborationMutationCommand(
        contract_version=WORKSPACE_COLLABORATION_CONTRACT_VERSION,
        surface="goals",
        action="create_objective",
        expected_revision=0,
        idempotency_key="objective-command-1",
        payload={"title": "Objective"},
    )

    with pytest.raises(ValueError, match="surface action is unavailable"):
        await _dispatch_mutation(
            actor=actor,
            command=command,
            request=cast("Any", SimpleNamespace()),
            background_tasks=BackgroundTasks(),
            current_user=cast("Any", SimpleNamespace(id="user-1")),
            db=cast("Any", SimpleNamespace()),
        )
