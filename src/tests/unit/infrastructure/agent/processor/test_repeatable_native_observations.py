"""Native observations stay fresh through both production tool dispatch paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.events.agent_events import AgentDoomLoopDetectedEvent, AgentObserveEvent
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.native_computer_use.contracts import READ_TOOL_NAMES, TOOL_NAMES
from src.infrastructure.agent.permission.manager import PermissionManager
from src.infrastructure.agent.permission.rules import PermissionAction, PermissionRule
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.tools import native_computer_use as native
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.truncation import OutputTruncator
from src.infrastructure.plugins.v2.agent_operation_tool_contributions import (
    lease_operation_tool_definitions_v2,
)

pytestmark = pytest.mark.unit


async def build_processor(monkeypatch, *, pipeline, tool_name):
    async def authorize(ctx, *_args, **_kwargs):
        return SimpleNamespace(call_id=ctx.call_id)

    authorize_call = AsyncMock(side_effect=authorize)
    monkeypatch.setattr(native, "authorize_native_call", authorize_call)
    broker = SimpleNamespace(
        describe_tools=AsyncMock(
            return_value=[
                {
                    "name": name,
                    "inputSchema": {"type": "object"},
                    # Untrusted device metadata cannot exempt actions from the guard.
                    "repeatable_observation": True,
                }
                for name in TOOL_NAMES
            ]
        ),
        devices=SimpleNamespace(list=AsyncMock(return_value=[])),
        request=AsyncMock(
            side_effect=[ToolResult(output=f"observation-{index}") for index in range(5)]
        ),
    )
    tools = await native.create_native_computer_tools(
        tenant_id="tenant", project_id="project", user_id="user", broker=broker
    )
    disposers = []

    class Operation:
        async def effect(self, setup, **_kwargs):
            disposers.append(setup())

    leased = await lease_operation_tool_definitions_v2(
        operation=Operation(), source_id="native", definitions=convert_tools(tools)
    )
    assert {
        definition.name for definition in leased.definitions if definition.repeatable_observation
    } == READ_TOOL_NAMES
    definitions = [definition for definition in leased.definitions if definition.name == tool_name]
    permissions = PermissionManager(ruleset=[PermissionRule("*", "*", PermissionAction.ALLOW)])
    permissions.ask = AsyncMock(return_value="reject")
    processor = SessionProcessor(
        config=ProcessorConfig(model="never-called", permission_timeout=0.1),
        tools=definitions,
        permission_manager=permissions,
    )
    processor._langfuse_context = {
        "tenant_id": "tenant",
        "project_id": "project",
        "user_id": "user",
        "conversation_id": "conversation",
    }
    if pipeline:
        processor._tool_pipeline = ToolPipeline(
            permission_manager=permissions,
            doom_detector=processor.doom_loop_detector,
            truncator=OutputTruncator(),
            hooks=ToolHookRegistry(),
        )
    return processor, broker, authorize_call, disposers


async def dispatch(processor, tool_name, index):
    part = ToolPart(call_id=f"call-{index}", tool=tool_name, status=ToolState.RUNNING)
    processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
    processor._pending_tool_calls[part.call_id] = part
    events = [
        event
        async for event in processor._execute_tool(
            "session", part.call_id, tool_name, {"app": "pid:12"}
        )
    ]
    return part, events


@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize("tool_name", ["computer_get_app_state", "computer_list_windows"])
async def test_five_identical_observations_each_reach_authorization_and_broker(
    monkeypatch, pipeline, tool_name
):
    processor, broker, authorize, _disposers = await build_processor(
        monkeypatch, pipeline=pipeline, tool_name=tool_name
    )
    for index in range(5):
        part, events = await dispatch(processor, tool_name, index)
        assert part.status == ToolState.COMPLETED
        assert part.output == f"observation-{index}"
        assert not any(isinstance(event, AgentDoomLoopDetectedEvent) for event in events)
    assert broker.request.await_count == authorize.await_count == 5
    assert [call.args[0].call_id for call in broker.request.await_args_list] == [
        f"call-{index}" for index in range(5)
    ]
    processor.permission_manager.ask.assert_not_awaited()


@pytest.mark.parametrize("pipeline", [False, True])
async def test_repeated_mutations_still_trigger_existing_loop_guard(monkeypatch, pipeline):
    processor, broker, _authorize, _disposers = await build_processor(
        monkeypatch, pipeline=pipeline, tool_name="computer_click"
    )
    for index in range(5):
        part, events = await dispatch(processor, "computer_click", index)
        if part.status == ToolState.ERROR:
            break
    assert part.status == ToolState.ERROR
    assert any(isinstance(event, AgentDoomLoopDetectedEvent) for event in events)
    # Both existing guards record pipeline calls, so its second invocation is blocked.
    assert broker.request.await_count == (1 if pipeline else 3)
    processor.permission_manager.ask.assert_awaited_once()
    assert processor.permission_manager.ask.call_args.kwargs["permission"] == "doom_loop"


@pytest.mark.parametrize("pipeline", [False, True])
async def test_repeatable_observations_keep_consecutive_error_guard(monkeypatch, pipeline):
    processor, broker, _authorize, _disposers = await build_processor(
        monkeypatch, pipeline=pipeline, tool_name="computer_get_app_state"
    )
    for _ in range(6):
        processor.doom_loop_detector.record_error("computer_get_app_state", "Device disconnected")
    part, events = await dispatch(processor, "computer_get_app_state", 0)
    assert part.status == ToolState.ERROR
    assert any(isinstance(event, AgentObserveEvent) and event.error for event in events)
    broker.request.assert_not_awaited()


@pytest.mark.parametrize("pipeline", [False, True])
async def test_repeatable_observations_remain_revocable(monkeypatch, pipeline):
    processor, broker, _authorize, disposers = await build_processor(
        monkeypatch, pipeline=pipeline, tool_name="computer_get_app_state"
    )
    disposers[0]()
    part, _events = await dispatch(processor, "computer_get_app_state", 0)
    assert part.status == ToolState.ERROR
    broker.request.assert_not_awaited()


@pytest.mark.parametrize("declaration", [None, "true", 1, False, True])
def test_only_explicit_boolean_metadata_exempts_repeat_checks(declaration):
    info = ToolInfo(
        name="computer_get_app_state",
        description="Observe",
        parameters={},
        permission="read",
        execute=AsyncMock(),
        repeatable_observation=declaration,
    )
    definition = convert_tools({info.name: info})[0]
    assert definition.repeatable_observation is (declaration is True)
