"""Single-authority coverage for one model-visible V2 turn ToolSet."""

from __future__ import annotations

from inspect import getsource
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

import pytest

from src.application.services.agent.tool_discovery import ToolDiscoveryService
from src.infrastructure.agent.core.react_agent_composition_mixin import CompositionMixin
from src.infrastructure.agent.core.react_agent_prompt_mixin import PromptMixin
from src.infrastructure.agent.core.react_agent_stream_mixin import StreamMixin
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


@pytest.mark.unit
def test_stream_is_the_only_turn_tool_set_resolution_site() -> None:
    stream_source = getsource(StreamMixin.stream)
    assert stream_source.count("_resolve_current_tools_from_runtime_v2(") == 1

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
