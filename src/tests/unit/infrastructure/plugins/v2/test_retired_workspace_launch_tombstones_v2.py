"""Retired Workspace entry points cannot retain a hidden DI business fallback."""

import ast
import inspect

import pytest

from src.infrastructure.agent.workspace.worker_launch import launch_worker_session
from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    _launch_workspace_retry_attempt,
)
from src.infrastructure.workspace_core.legacy_runtime import LegacyWorkspaceRuntimeRetiredError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("function", [launch_worker_session, _launch_workspace_retry_attempt])
def test_retirement_call_is_the_final_statement(function):
    node = ast.parse(inspect.getsource(function)).body[0]
    assert isinstance(node, ast.AsyncFunctionDef)
    terminal = node.body[-1]
    assert isinstance(terminal, ast.Expr)
    assert isinstance(terminal.value, ast.Call)
    assert isinstance(terminal.value.func, ast.Name)
    assert terminal.value.func.id == "legacy_workspace_runtime_retired"


async def test_worker_launch_preserves_retirement_before_inspecting_task():
    with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Workspace worker launch"):
        await launch_worker_session(
            workspace_id="retired", task=None, worker_agent_id="", actor_user_id="actor"
        )


async def test_retry_launch_preserves_retirement_before_any_database_access():
    with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Workspace retry attempt launch"):
        await _launch_workspace_retry_attempt(
            workspace_id="retired",
            root_goal_task_id="root",
            workspace_task_id="task",
            attempt_id="attempt",
            actor_user_id="actor",
            leader_agent_id="leader",
            retry_feedback="",
        )
