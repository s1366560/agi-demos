"""Tests for ReActAgent execution-path and selection integration."""

from types import SimpleNamespace
from typing import Any, Dict

import pytest

from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.agent.routing.execution_router import ExecutionPath


class _MockTool:
    def __init__(self, name: str, description: str = "tool") -> None:
        self.name = name
        self.description = description

    async def execute(self, **kwargs: Any) -> str:  # noqa: ANN401
        return "ok"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}


@pytest.mark.unit
def test_decide_execution_path_respects_forced_subagent() -> None:
    """Forced subagent instruction should route to SUBAGENT path."""
    agent = ReActAgent(model="test-model", tools={"read": _MockTool("read")})
    decision = agent._decide_execution_path(
        message="help me",
        conversation_context=[],
        forced_subagent_name="coder",
    )

    assert decision.path == ExecutionPath.SUBAGENT
    assert decision.target == "coder"
    assert decision.metadata.get("domain_lane") == "subagent"
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
def test_router_mode_threshold_skips_subagent_routing_when_below_threshold() -> None:
    """Subagent routing should be bypassed when tool count is below router threshold."""
    tools = {"read": _MockTool("read"), "write": _MockTool("write")}
    agent = ReActAgent(
        model="test-model",
        tools=tools,
        enable_subagent_as_tool=False,
        router_mode_tool_count_threshold=10,
    )
    agent._match_subagent = lambda _query: SimpleNamespace(  # type: ignore[assignment]
        subagent=SimpleNamespace(name="coder"),
        confidence=0.9,
        match_reason="forced test match",
    )

    decision = agent._decide_execution_path(
        message="coder function",
        conversation_context=[],
    )

    assert decision.path == ExecutionPath.REACT_LOOP
    assert decision.metadata.get("router_mode_enabled") is False
    assert decision.metadata.get("router_fabric_version") == "lane-v1"


@pytest.mark.unit
def test_router_mode_threshold_enables_subagent_routing_when_above_threshold() -> None:
    """Subagent routing should run when tool count exceeds router threshold."""
    tools = {f"tool_{idx}": _MockTool(f"tool_{idx}") for idx in range(4)}
    agent = ReActAgent(
        model="test-model",
        tools=tools,
        enable_subagent_as_tool=False,
        router_mode_tool_count_threshold=2,
    )
    agent._match_subagent = lambda _query: SimpleNamespace(  # type: ignore[assignment]
        subagent=SimpleNamespace(name="coder"),
        confidence=0.9,
        match_reason="forced test match",
    )

    decision = agent._decide_execution_path(
        message="coder function",
        conversation_context=[],
    )

    assert decision.path == ExecutionPath.SUBAGENT
    assert decision.target == "coder"
    assert decision.metadata.get("router_mode_enabled") is True
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
