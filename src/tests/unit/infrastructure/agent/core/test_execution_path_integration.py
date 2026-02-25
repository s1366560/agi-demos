"""Tests for ReActAgent execution-path and selection integration."""

from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.agent.routing.execution_router import ExecutionPath


class _MockTool:
    def __init__(self, name: str, description: str = "tool") -> None:
        self.name = name
        self.description = description

    async def execute(self, **kwargs: Any) -> str:
        return "ok"

    def get_parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}


@pytest.mark.unit
def test_decide_execution_path_respects_forced_subagent() -> None:
    """Forced subagent instruction should route to REACT_LOOP with forced_subagent metadata."""
    agent = ReActAgent(model="test-model", tools={"read": _MockTool("read")})
    decision = agent._decide_execution_path(
        message="help me",
        conversation_context=[],
        forced_subagent_name="coder",
    )

    assert decision.path == ExecutionPath.REACT_LOOP
    assert decision.target == "coder"
    assert decision.metadata.get("forced_subagent") == "coder"
    assert decision.metadata.get("router_fabric_version") == "lane-v1"


@pytest.mark.unit
def test_get_current_tools_applies_selection_pipeline_budget() -> None:
    """Selection pipeline should reduce tool count under configured max budget."""
    tools = {f"tool_{idx}": _MockTool(f"tool_{idx}") for idx in range(20)}
    tools["read"] = _MockTool("read")
    tools["write"] = _MockTool("write")
    agent = ReActAgent(model="test-model", tools=tools, tool_selection_max_tools=5)

    selection_context = agent._build_tool_selection_context(
        tenant_id="tenant-1",
        project_id="project-1",
        user_message="read file",
        conversation_context=[{"role": "user", "content": "read file"}],
        effective_mode="build",
    )
    selected_tools, selected_defs = agent._get_current_tools(selection_context=selection_context)

    assert len(selected_tools) <= agent._tool_selection_max_tools
    assert len(selected_defs) <= agent._tool_selection_max_tools
    assert any(step.stage == "semantic_ranker_stage" for step in agent._last_tool_selection_trace)


@pytest.mark.unit
def test_selection_context_includes_policy_layers_and_agent_policy() -> None:
    """Selection context should carry layered policy and plan-mode deny list."""
    agent = ReActAgent(
        model="test-model",
        tools={"read": _MockTool("read"), "plugin_manager": _MockTool("plugin_manager")},
        tool_policy_layers={"tenant": {"allow_tools": ["read"]}},
    )

    selection_context = agent._build_tool_selection_context(
        tenant_id="tenant-1",
        project_id="project-1",
        user_message="plan this work",
        conversation_context=[{"role": "user", "content": "plan this work"}],
        effective_mode="plan",
    )
    metadata = selection_context.metadata or {}

    assert "policy_layers" in metadata
    assert metadata["policy_layers"]["tenant"]["allow_tools"] == ["read"]
    assert "plugin_manager" in metadata["deny_tools"]
    assert "plugin_manager" in metadata["policy_agent"]["deny_tools"]


@pytest.mark.unit
def test_no_subagents_routes_to_react_loop() -> None:
    """Without subagents, _decide_execution_path should return REACT_LOOP."""
    tools = {"read": _MockTool("read"), "write": _MockTool("write")}
    agent = ReActAgent(
        model="test-model",
        tools=tools,
        enable_subagent_as_tool=False,
    )

    decision = agent._decide_execution_path(
        message="do something",
        conversation_context=[],
    )

    assert decision.path == ExecutionPath.REACT_LOOP
    assert decision.metadata.get("router_fabric_version") == "lane-v1"


@pytest.mark.unit
def test_subagents_with_tool_mode_disabled_routes_to_react_loop() -> None:
    """With subagents and enable_subagent_as_tool=False, routing returns REACT_LOOP."""
    tools = {f"tool_{idx}": _MockTool(f"tool_{idx}") for idx in range(4)}
    mock_subagent = SimpleNamespace(
        id="sa-1", name="coder", display_name="Coder", enabled=True,
        model=None, temperature=0.7, max_tokens=4096, max_iterations=20,
        system_prompt="You code.", allowed_tools=["*"],
        allowed_skills=[], allowed_mcp_servers=[],
        trigger=SimpleNamespace(keywords=["code"]),
    )
    agent = ReActAgent(
        model="test-model",
        tools=tools,
        subagents=[mock_subagent],
        enable_subagent_as_tool=False,
    )

    decision = agent._decide_execution_path(
        message="coder function",
        conversation_context=[],
    )

    assert decision.path == ExecutionPath.REACT_LOOP
    assert decision.metadata.get("router_fabric_version") == "lane-v1"


@pytest.mark.unit
def test_build_tool_selection_context_carries_domain_lane_metadata() -> None:
    """Selection context should include routed domain lane when provided."""
    agent = ReActAgent(model="test-model", tools={"read": _MockTool("read")})

    selection_context = agent._build_tool_selection_context(
        tenant_id="tenant-1",
        project_id="project-1",
        user_message="search memory graph",
        conversation_context=[{"role": "user", "content": "search memory graph"}],
        effective_mode="build",
        routing_metadata={
            "domain_lane": "data",
            "router_mode_enabled": True,
            "route_id": "route_123",
            "trace_id": "trace_123",
        },
    )

    assert selection_context.metadata.get("domain_lane") == "data"
    assert selection_context.metadata.get("route_id") == "route_123"
    assert selection_context.metadata.get("trace_id") == "trace_123"
    assert selection_context.metadata.get("routing_metadata", {}).get("router_mode_enabled") is True
