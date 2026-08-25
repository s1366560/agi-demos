"""Regression coverage for Workspace Core-owned task route contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers import workspace_tasks


class _AccessTrap:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"retired workspace task handler accessed {name}")


def _handler_cases() -> list[tuple[str, dict[str, Any]]]:
    task = {"task_id": "task-1"}
    return [
        (
            "create_workspace_task",
            {"body": workspace_tasks.WorkspaceTaskCreateRequest(title="Task")},
        ),
        (
            "list_workspace_tasks",
            {"status_filter": None, "limit": 50, "offset": 0},
        ),
        ("get_workspace_task", task),
        ("get_workspace_task_experience", task),
        ("get_workspace_task_execution_session", task),
        (
            "apply_workspace_task_recovery_action",
            {
                **task,
                "body": workspace_tasks.TaskRecoveryActionRequest(action="retry_launch"),
            },
        ),
        (
            "update_workspace_task",
            {**task, "body": workspace_tasks.WorkspaceTaskUpdateRequest(title="Updated")},
        ),
        ("delete_workspace_task", task),
        (
            "assign_workspace_task_to_agent",
            {
                **task,
                "body": workspace_tasks.AssignAgentRequest(workspace_agent_id="binding-1"),
            },
        ),
        ("unassign_workspace_task_from_agent", task),
        ("claim_workspace_task", task),
        ("start_workspace_task", task),
        ("block_workspace_task", task),
        ("complete_workspace_task", task),
    ]


@pytest.mark.unit
def test_workspace_task_module_keeps_contract_schemas_without_local_di() -> None:
    assert {
        "WorkspaceTaskCreateRequest",
        "WorkspaceTaskUpdateRequest",
        "AssignAgentRequest",
        "WorkspaceTaskResponse",
        "WorkspaceTaskExperienceResponse",
        "TaskExecutionSessionResponse",
        "TaskRecoveryActionRequest",
        "TaskRecoveryActionResponse",
    }.issubset(vars(workspace_tasks))
    assert {
        "DIContainer",
        "WorkspaceTaskService",
        "WorkspaceTaskCommandService",
        "WorkspaceTaskExperienceService",
        "WorkspaceTaskEventPublisher",
        "TaskExecutionSessionMonitor",
        "get_db",
        "get_container_with_db",
        "_get_workspace_task_service",
        "_get_workspace_task_command_service",
        "_get_workspace_task_experience_service",
        "_get_task_execution_session_monitor",
        "_get_workspace_task_event_publisher",
        "_to_response",
        "_to_http_error",
        "_publish_task_execution_session_event",
        "_publish_recovery_result_events",
    }.isdisjoint(vars(workspace_tasks))


@pytest.mark.unit
@pytest.mark.parametrize(("handler_name", "extra"), _handler_cases())
async def test_legacy_workspace_task_handlers_fail_closed_without_local_di(
    handler_name: str,
    extra: dict[str, Any],
) -> None:
    handler = cast(
        Callable[..., Awaitable[object]],
        getattr(workspace_tasks, handler_name),
    )
    kwargs: dict[str, Any] = {
        "workspace_id": "workspace-1",
        "request": _AccessTrap(),
        "current_user": _AccessTrap(),
        "db": _AccessTrap(),
        **extra,
    }

    with pytest.raises(HTTPException) as exc_info:
        await handler(**kwargs)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == {
        "code": "WORKSPACE_CORE_UNAVAILABLE",
        "reason": "workspace_core_unavailable",
        "detail": "Workspace Core is unavailable",
    }


@pytest.mark.unit
def test_workspace_task_contract_models_remain_stable() -> None:
    assert set(workspace_tasks.WorkspaceTaskCreateRequest.model_fields) == {
        "title",
        "description",
        "assignee_user_id",
        "metadata",
        "preferred_language",
        "priority",
        "estimated_effort",
        "blocker_reason",
    }
    assert set(workspace_tasks.TaskRecoveryActionResponse.model_fields) == {
        "workspace_id",
        "task_id",
        "action",
        "status",
        "message",
        "conversation_id",
        "attempt_id",
        "outbox_id",
        "session",
    }
