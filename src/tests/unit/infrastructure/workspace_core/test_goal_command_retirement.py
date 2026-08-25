"""Regression coverage for retired local Workspace-backed slash-goal data paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from src.infrastructure.agent.commands import goal_mode
from src.infrastructure.workspace_core.legacy_runtime import (
    LegacyWorkspaceRuntimeRetiredError,
)

type _GoalCall = Callable[[], Awaitable[object]]


def _legacy_goal_calls() -> tuple[_GoalCall, ...]:
    return (
        lambda: goal_mode.create_workspace_for_goal(
            tenant_id="tenant-1",
            project_id="project-1",
            actor_user_id="user-1",
            goal_text="Ship V2",
            conversation_id="conversation-1",
        ),
        lambda: goal_mode.create_workspace_goal(
            workspace_id="workspace-1",
            actor_user_id="user-1",
            goal_text="Ship V2",
            conversation_id="conversation-1",
            preferred_language="zh-CN",
        ),
        lambda: goal_mode.list_workspace_goals(
            workspace_id="workspace-1",
            actor_user_id="user-1",
            limit=5,
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize("call", _legacy_goal_calls())
async def test_legacy_goal_data_paths_fail_closed_before_opening_local_sql(
    monkeypatch: pytest.MonkeyPatch,
    call: _GoalCall,
) -> None:
    def local_sql_trap() -> None:
        raise AssertionError("retired slash-goal path opened a local SQL session")

    monkeypatch.setattr(goal_mode, "async_session_factory", local_sql_trap, raising=False)

    with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Avernet Workspace Core"):
        await call()


@pytest.mark.unit
def test_goal_command_module_has_no_static_workspace_service_composition() -> None:
    retired_names = {
        "WorkspaceService",
        "WorkspaceTaskService",
        "WorkspaceTaskCommandService",
        "WorkspaceTaskEventPublisher",
        "SqlConversationRepository",
        "async_session_factory",
        "_publish_goal_events",
        "_publish_workspace_events",
        "_schedule_pending_ticks",
        "_bind_existing_conversation_to_goal",
        "_bind_conversation_to_workspace",
        "_workspace_name_for_goal",
        "_task_status_value",
    }

    assert retired_names.isdisjoint(vars(goal_mode))
