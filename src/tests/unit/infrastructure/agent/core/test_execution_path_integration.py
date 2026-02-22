"""Tests for ReActAgent execution-path and selection integration."""

from typing import Any, Dict

import pytest

from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.agent.routing.execution_router import ExecutionPath


class _MockTool:
    def __init__(self, name: str, description: str = "tool") -> None:
        self.name = name
        self.description = description

    async def execute(self, **kwargs: Any) -> str:
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
