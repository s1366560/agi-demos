from __future__ import annotations

from types import MappingProxyType

import pytest

from src.domain.model.agent.subagent import AgentTrigger, SubAgent
from src.domain.model.agent.tool_policy import ToolPolicy, ToolPolicyPrecedence
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.core.processor import ToolDefinition
from src.infrastructure.agent.core.subagent_router import SubAgentRouter
from src.infrastructure.agent.core.subagent_tool_set_v2 import InheritedToolSetV2
from src.infrastructure.agent.core.subagent_tools import (
    SubAgentToolBuilder,
    SubAgentToolBuilderDeps,
)
from src.infrastructure.plugins.v2.tool_set import ToolSetV2


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
def test_subagent_tool_builder_applies_policy_to_inherited_parent_tool_set() -> None:
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
    builder = SubAgentToolBuilder(
        SubAgentToolBuilderDeps(subagent_run_registry_resolver=lambda: object())
    )
    inherited = InheritedToolSetV2(
        tool_set=ToolSetV2(
            tools=MappingProxyType(raw_tools),
            definitions=tuple(tool_definitions),
        ),
        generation_descriptor=PluginGenerationDescriptorV2(
            profile_id="test",
            generation=1,
            digest="1" * 64,
        ),
        owner_operation_id="parent-turn",
    )

    filtered, existing_tool_names = builder.filter_tools(
        subagent,
        inherited_tool_set=inherited,
    )

    assert [tool.name for tool in filtered] == ["read"]
    assert existing_tool_names == {"read"}
