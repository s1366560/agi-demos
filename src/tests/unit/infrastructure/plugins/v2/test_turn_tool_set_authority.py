"""Single-authority coverage for one model-visible V2 turn ToolSet."""

from __future__ import annotations

from inspect import getsource
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

import pytest

from src.application.services.agent.tool_discovery import ToolDiscoveryService
from src.domain.model.agent.skill import Skill
from src.infrastructure.agent.core.react_agent_composition_mixin import CompositionMixin
from src.infrastructure.agent.core.react_agent_prompt_mixin import PromptMixin
from src.infrastructure.agent.core.react_agent_stream_mixin import (
    StreamMixin,
    _finalize_turn_tool_set_v2,
)
from src.infrastructure.agent.plugins.selection_pipeline import (
    ToolSelectionContext,
    ToolSelectionTraceStep,
)
from src.infrastructure.agent.processor import ProcessorConfig, ToolDefinition
from src.infrastructure.plugins.v2.agent_runtime_dispatcher import (
    PinnedAgentRuntimeDispatcherV2,
)
from src.infrastructure.plugins.v2.tool_set import ToolSetV2


async def _execute_tool() -> str:
    return "ok"


class _SandboxTool:
    sandbox_id = "sandbox-from-pinned-generation"


class _TurnConsumerAgent(CompositionMixin, StreamMixin):
    _tool_selection_max_tools = 8
    _use_dynamic_tools = True
    _tool_provider = staticmethod(
        lambda: (_ for _ in ()).throw(
            AssertionError("processor must not refresh tools inside a pinned turn")
        )
    )

    def _get_current_tools(self, selection_context=None):
        _ = selection_context
        raise AssertionError("turn consumers must not read the native tool collection")


def _turn_tool_set() -> ToolSetV2:
    raw_tool = _SandboxTool()
    definition = ToolDefinition(
        name="enabled_tool",
        description="Enabled by the pinned V2 generation",
        parameters={"type": "object", "properties": {}},
        execute=_execute_tool,
        _tool_instance=raw_tool,
    )
    return ToolSetV2(
        tools=MappingProxyType({"enabled_tool": raw_tool}),
        definitions=(definition,),
        selection_trace=(
            ToolSelectionTraceStep(
                stage="profile_filter",
                before_count=2,
                after_count=1,
                removed_tools=("disabled_tool",),
            ),
        ),
    )


def _named_tool_set(*names: str) -> ToolSetV2:
    tools = {name: object() for name in names}
    definitions = tuple(
        ToolDefinition(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
            execute=_execute_tool,
        )
        for name in names
    )
    return ToolSetV2(tools=MappingProxyType(tools), definitions=definitions)


@pytest.mark.unit
def test_stream_is_the_only_turn_tool_set_resolution_site() -> None:
    stream_source = getsource(StreamMixin.stream)
    assert stream_source.count("_resolve_current_tools_from_runtime_v2(") == 1
    assert "from src.infrastructure.plugins.v2.runtime import RuntimeV2Error" not in stream_source

    for consumer in (
        PromptMixin._build_system_prompt,
        PromptMixin._build_primary_agent_prompt,
        CompositionMixin._extract_sandbox_id_from_tools,
        StreamMixin._stream_prepare_tools,
        StreamMixin._stream_create_processor_config,
        ToolDiscoveryService.get_available_tools,
    ):
        source = getsource(consumer)
        assert "_get_current_tools(" not in source
        assert "_resolve_current_tools_from_runtime_v2(" not in source


@pytest.mark.unit
def test_operation_tool_contributions_are_registered_before_turn_resolution() -> None:
    stream_source = getsource(StreamMixin.stream)
    resolve_offset = stream_source.index("_resolve_current_tools_from_runtime_v2(")
    finalize_offset = stream_source.index("turn_tool_set = _finalize_turn_tool_set_v2(")
    resource_sync_offset = stream_source.index("# Phase 6e:")

    assert stream_source.index("activate_skill_mcp_operation_tools_v2(") < resolve_offset
    assert stream_source.index("contribute_operation_tool_definitions_v2(") < resolve_offset
    assert (
        "forced_operation_tool_names=mcp_tool_names"
        in stream_source[finalize_offset:resource_sync_offset]
    )
    assert "_skill_mcp_tools" not in stream_source
    assert "_stream_inject_subagent_tools(" not in stream_source[resolve_offset:]


@pytest.mark.unit
def test_turn_policy_filters_dynamic_contributions_with_the_base_tool_set() -> None:
    tool_set = _named_tool_set(
        "base_tool",
        "mcp_echo",
        "delegate_to_subagent",
        "denied_dynamic",
    )
    matched_skill = Skill.create(
        tenant_id="tenant-a",
        name="mcp-skill",
        description="Use the turn MCP tool",
        tools=["base_tool"],
    )

    forced = _finalize_turn_tool_set_v2(
        tool_set,
        is_forced=True,
        matched_skill=matched_skill,
        workspace_root_task=None,
        is_workspace_conversation=False,
        allow_tools=("mcp_echo", "delegate_to_subagent"),
        deny_tools=("delegate_to_subagent",),
        forced_operation_tool_names=("mcp_echo",),
    )
    ordinary = _finalize_turn_tool_set_v2(
        tool_set,
        is_forced=False,
        matched_skill=None,
        workspace_root_task=None,
        is_workspace_conversation=False,
        allow_tools=("base_tool", "mcp_echo", "delegate_to_subagent"),
        deny_tools=("delegate_to_subagent",),
    )

    assert tuple(forced.tools) == ("mcp_echo",)
    assert tuple(ordinary.tools) == ("base_tool", "mcp_echo")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_consumers_share_exact_pinned_tool_set_without_refresh() -> None:
    agent = _TurnConsumerAgent()
    tool_set = _turn_tool_set()
    selection_context = ToolSelectionContext(
        tenant_id="tenant-a",
        project_id="project-a",
        metadata={"route_id": "route-a", "trace_id": "trace-a"},
    )

    assert agent._extract_sandbox_id_from_tools(tool_set=tool_set) == (
        "sandbox-from-pinned-generation"
    )

    events = list(
        agent._stream_prepare_tools(
            selection_context,
            is_forced=False,
            matched_skill=None,
            tool_set=tool_set,
        )
    )
    assert [event["type"] for event in events] == ["selection_trace", "policy_filtered"]
    assert events[0]["data"]["final_count"] == 1

    dispatcher = PinnedAgentRuntimeDispatcherV2()
    operation = SimpleNamespace(require=lambda _service: dispatcher)
    base_config = ProcessorConfig(
        model="test-model",
        tool_provider=lambda: [
            ToolDefinition(
                name="disabled_tool",
                description="Must never refresh into this turn",
                parameters={"type": "object", "properties": {}},
                execute=_execute_tool,
            )
        ],
    )
    with patch(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        return_value=operation,
    ):
        request_config = agent._stream_create_processor_config(
            base_config,
            selection_context,
            tool_set=tool_set,
        )

    assert request_config.tool_provider is None
    assert request_config.plugin_event_dispatcher is dispatcher

    discovery = ToolDiscoveryService()
    inventory = await discovery.get_available_tools(
        project_id="project-a",
        tenant_id="tenant-a",
        tool_set=tool_set,
    )
    assert inventory == [
        {
            "name": "enabled_tool",
            "description": "Enabled by the pinned V2 generation",
        }
    ]
