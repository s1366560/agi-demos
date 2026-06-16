from __future__ import annotations

import pytest

from src.domain.model.agent.subagent import AgentTrigger, SubAgent
from src.domain.model.agent.tool_policy import ToolPolicy, ToolPolicyPrecedence
from src.infrastructure.agent.core.processor import ToolDefinition
from src.infrastructure.agent.core.subagent_router import SubAgentRouter
from src.infrastructure.agent.core.subagent_tools import (
    SubAgentToolBuilder,
    SubAgentToolBuilderDeps,
)


def _make_subagent(**overrides: object) -> SubAgent:
    return SubAgent(
        id="worker-id",
        tenant_id="tenant-1",
        name="worker",
        display_name="Worker",
        system_prompt="You are a worker.",
        trigger=AgentTrigger(description="Use for worker tasks."),
        **overrides,
    )


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(name, "", {}, lambda **_: None)


@pytest.mark.unit
def test_subagent_router_applies_structured_tool_policy_with_canonical_names() -> None:
    subagent = _make_subagent(
        allowed_tools=["Read", "Bash", "Grep"],
        tool_policy=ToolPolicy(
            allow=("Read", "Bash"),
            deny=("Bash", "Grep"),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        ),
    )
    router = SubAgentRouter([subagent])

    filtered = router.filter_tools(
        subagent,
        {
            "read": object(),
            "bash": object(),
            "grep": object(),
            "write": object(),
        },
    )

    assert list(filtered) == ["read", "bash"]


@pytest.mark.unit
def test_subagent_tool_builder_fallback_applies_subagent_tool_policy() -> None:
    subagent = _make_subagent(
        allowed_tools=["Read", "Bash", "Grep"],
        tool_policy=ToolPolicy(
            allow=("Read",),
            deny=("Bash",),
            precedence=ToolPolicyPrecedence.DENY_FIRST,
        ),
    )
    raw_tools = {"read": object(), "bash": object(), "grep": object()}
    tool_definitions = [_tool("read"), _tool("bash"), _tool("grep")]
    builder = SubAgentToolBuilder(SubAgentToolBuilderDeps(subagent_run_registry=object()))
    builder.deps.get_current_tools_fn = lambda: (raw_tools, tool_definitions)

    filtered, existing_tool_names = builder.filter_tools(subagent)

    assert [tool.name for tool in filtered] == ["read"]
    assert existing_tool_names == {"read"}
