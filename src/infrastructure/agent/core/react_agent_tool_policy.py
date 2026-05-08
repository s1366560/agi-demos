"""Pure tool-policy filters extracted from ``react_agent.py`` (PR-7a phase 3).

Each function here is referentially transparent: input → output, no side
effects, no ``self`` dependency. The ``ReActAgent`` class methods retain
thin delegators so tests calling ``ReActAgent._filter_tools_by_name_policy``
or ``agent._with_workspace_worker_tool_allowlist`` keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_WORKSPACE_PLANNER_ID

from .react_agent_profile import (
    _WORKSPACE_LEADER_REPLAN_TOOL_NAMES,
    _WORKSPACE_WORKER_CODE_TOOL_NAMES,
    _WORKSPACE_WORKER_REPORT_TOOL_NAMES,
    AgentRuntimeProfile,
)
from .tool_name_policy import canonical_tool_policy_names

if TYPE_CHECKING:
    from .processor import ToolDefinition

WORKSPACE_ROOT_TOOL_BYPASS_NAMES: frozenset[str] = frozenset(
    {
        "agent_spawn",
        "agent_send",
        "agent_sessions",
        "agent_history",
        "agent_stop",
        "workspace_chat_send",
    }
)


def filter_workspace_root_tools(
    tools_to_use: list[ToolDefinition],
    workspace_root_task: object | None,
) -> list[ToolDefinition]:
    """Strip generic agent bypass tools when running as workspace root."""
    if workspace_root_task is None:
        return tools_to_use
    return [tool for tool in tools_to_use if tool.name not in WORKSPACE_ROOT_TOOL_BYPASS_NAMES]


def filter_tools_by_name_policy(
    tools_to_use: list[ToolDefinition],
    *,
    allow_tools: Sequence[str] | None,
    deny_tools: Sequence[str] | None,
) -> list[ToolDefinition]:
    """Apply final hard allow/deny filtering to the executable tool list."""
    known_tool_names = [tool.name for tool in tools_to_use]
    raw_allow: set[str] = set(canonical_tool_policy_names(allow_tools, known_tool_names))
    allow: set[str] = set() if "*" in raw_allow else raw_allow
    deny: set[str] = set(canonical_tool_policy_names(deny_tools, known_tool_names))
    if not allow and not deny:
        return tools_to_use
    return [
        tool for tool in tools_to_use if (not allow or tool.name in allow) and tool.name not in deny
    ]


def with_workspace_worker_tool_allowlist(
    runtime_profile: AgentRuntimeProfile,
) -> AgentRuntimeProfile:
    """Ensure workspace workers can inspect/edit/report despite persona allowlists."""
    if (
        runtime_profile.selected_agent is not None
        and runtime_profile.selected_agent.id == BUILTIN_WORKSPACE_PLANNER_ID
    ):
        return runtime_profile
    if not runtime_profile.allow_tools or "*" in runtime_profile.allow_tools:
        return runtime_profile
    required_tools = list(_WORKSPACE_WORKER_REPORT_TOOL_NAMES)
    if not runtime_profile.tenant_agent_config.enabled_tools:
        required_tools.extend(_WORKSPACE_WORKER_CODE_TOOL_NAMES)
    expanded = sorted(
        {
            *canonical_tool_policy_names(runtime_profile.allow_tools),
            *required_tools,
        }
    )
    return replace(runtime_profile, allow_tools=expanded)


def with_workspace_leader_replan_tool_allowlist(
    runtime_profile: AgentRuntimeProfile,
) -> AgentRuntimeProfile:
    """Restrict leader remediation turns to task-ledger inspection and updates."""
    allowed = set(_WORKSPACE_LEADER_REPLAN_TOOL_NAMES)
    return replace(
        runtime_profile,
        allow_tools=sorted(allowed),
        deny_tools=sorted(set(runtime_profile.deny_tools) - allowed),
    )


__all__ = [
    "WORKSPACE_ROOT_TOOL_BYPASS_NAMES",
    "filter_tools_by_name_policy",
    "filter_workspace_root_tools",
    "with_workspace_leader_replan_tool_allowlist",
    "with_workspace_worker_tool_allowlist",
]
