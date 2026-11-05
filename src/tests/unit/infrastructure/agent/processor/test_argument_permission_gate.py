"""Every generic permission gate consumes the tool's declared argument effects."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.permission.manager import PermissionManager
from src.infrastructure.agent.permission.rules import PermissionAction, PermissionRule
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.executor import ExecutionContext, ToolExecutor
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.todo_tools import todowrite_tool
from src.infrastructure.agent.tools.truncation import OutputTruncator

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("entrypoint", ["processor", "pipeline", "executor"])
@pytest.mark.parametrize("progress", [False, True])
async def test_progress_only_effect_is_allowed_but_plan_replacement_keeps_write_boundary(
    entrypoint, progress
):
    manager = PermissionManager(
        ruleset=[
            PermissionRule("workspace_task_write", "*", PermissionAction.DENY),
            PermissionRule("conversation_progress", "*", PermissionAction.ALLOW),
        ]
    )
    tool = ToolDefinition(
        name="opaque_operation",
        description="Exact declared effects",
        parameters=todowrite_tool.parameters,
        permission="workspace_task_write",
        permission_resolver=todowrite_tool.permission_resolver,
        execute=AsyncMock(),
    )
    arguments = (
        {"action": "update", "todo_id": "exact-task", "todos": [{"status": "in_progress"}]}
        if progress
        else {"action": "replace", "todos": [{"content": "new plan"}]}
    )
    part = ToolPart(call_id="call", tool=tool.name, input=arguments, status=ToolState.RUNNING)
    if entrypoint == "pipeline":
        gate = ToolPipeline(manager, MagicMock(), OutputTruncator(), ToolHookRegistry())
        result = await gate._check_permission(
            tool,
            arguments,
            ToolContext(
                session_id="current",
                conversation_id="current",
                message_id="message",
                call_id="call",
                agent_name="fixture",
            ),
        )
    elif entrypoint == "executor":
        gate = ToolExecutor(MagicMock(), manager)
        events = [
            event
            async for event in gate._check_permission(
                tool.name, tool, arguments, part, ExecutionContext(session_id="current"), "call"
            )
        ]
        result = events or None
    else:
        gate = SessionProcessor(
            config=ProcessorConfig(model="never-called"), tools=[tool], permission_manager=manager
        )
        result = await gate._check_tool_permission(
            "current", "call", tool.name, arguments, part, tool
        )
    assert (result is None) is progress
    tool.execute.assert_not_called()


@pytest.mark.parametrize("entrypoint", ["processor", "pipeline", "executor"])
async def test_ask_uses_the_resolved_effect_without_promoting_it_to_a_write(entrypoint):
    manager = PermissionManager(
        ruleset=[
            PermissionRule("workspace_task_write", "*", PermissionAction.DENY),
            PermissionRule("conversation_progress", "*", PermissionAction.ASK),
        ]
    )
    manager.ask = AsyncMock(return_value="approve")
    tool = ToolDefinition(
        name="opaque_operation",
        description="Declared effect",
        parameters=todowrite_tool.parameters,
        permission="workspace_task_write",
        permission_resolver=todowrite_tool.permission_resolver,
        execute=AsyncMock(),
    )
    args = {"action": "update", "todo_id": "exact-task", "todos": [{"status": "in_progress"}]}
    part = ToolPart(call_id="call", tool=tool.name, input=args, status=ToolState.RUNNING)
    if entrypoint == "processor":
        gate = SessionProcessor(
            config=ProcessorConfig(model="never-called"), tools=[tool], permission_manager=manager
        )
        coordinator = MagicMock(
            prepare_request=AsyncMock(return_value="permission"),
            wait_for_response=AsyncMock(return_value=True),
        )
        gate._get_hitl_coordinator = lambda: coordinator
        pending = await gate._check_tool_permission("current", "call", tool.name, args, part, tool)
        events = [event async for event in pending]
        assert events
        assert (
            coordinator.prepare_request.call_args.kwargs["request_data"]["permission_type"]
            == "conversation_progress"
        )
    elif entrypoint == "pipeline":
        gate = ToolPipeline(manager, MagicMock(), OutputTruncator(), ToolHookRegistry())
        assert (
            await gate._check_permission(
                tool,
                args,
                ToolContext(
                    session_id="current",
                    conversation_id="current",
                    message_id="message",
                    call_id="call",
                    agent_name="fixture",
                ),
            )
            is None
        )
        assert manager.ask.call_args.kwargs["permission"] == "conversation_progress"
    else:
        gate = ToolExecutor(MagicMock(), manager)
        events = [
            event
            async for event in gate._check_permission(
                tool.name, tool, args, part, ExecutionContext(session_id="current"), "call"
            )
        ]
        assert events[0].permission == "conversation_progress"
        assert manager.ask.call_args.kwargs["permission"] == "conversation_progress"
    tool.execute.assert_not_called()
