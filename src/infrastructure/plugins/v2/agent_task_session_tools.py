"""Generation-owned contributions for prepared task and session tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, cast

from src.infrastructure.agent.core.tool_converter import convert_tools

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .tool_set import ToolContributionDisposerV2, ToolSetCatalogProtocolV2, ToolSetV2

AGENT_TODO_TOOLS_MODULE_V2 = "builtin://memstack/agent/tool/todo"
AGENT_TODO_TOOLS_SOURCE_V2 = "builtin-agent-todo-tools"
AGENT_TODO_TOOL_NAMES_V2 = frozenset({"todoread", "todowrite"})

AGENT_PEER_SESSION_TOOLS_MODULE_V2 = "builtin://memstack/agent/tool/peer-session"
AGENT_PEER_SESSION_TOOLS_SOURCE_V2 = "builtin-agent-peer-session-tools"
AGENT_PEER_SESSION_TOOL_NAMES_V2 = frozenset(
    {
        "peer_sessions_history",
        "peer_sessions_list",
        "peer_sessions_send",
    }
)

AGENT_SESSION_STATUS_TOOL_MODULE_V2 = "builtin://memstack/agent/tool/session-status"
AGENT_SESSION_STATUS_TOOL_SOURCE_V2 = "builtin-agent-session-status-tool"
AGENT_SESSION_STATUS_TOOL_NAMES_V2 = frozenset({"session_status"})

AGENT_CRON_TOOL_MODULE_V2 = "builtin://memstack/agent/tool/cron"
AGENT_CRON_TOOL_SOURCE_V2 = "builtin-agent-cron-tool"
AGENT_CRON_TOOL_NAMES_V2 = frozenset({"cron"})


def _prepared_tool_group_v2(
    *,
    agent: object,
    selection_context: object | None,
    label: str,
    required_tool_names: frozenset[str],
) -> ToolSetV2:
    """Select exact Worker-prepared instances for one declared tool group."""
    get_current_tools = getattr(agent, "_get_current_tools", None)
    if not callable(get_current_tools):
        raise RuntimeV2Error(
            "invalid_tool_contribution",
            f"{label} contribution requires callable _get_current_tools",
        )
    _ = selection_context
    result: object = get_current_tools(selection_context=None)
    if not isinstance(result, tuple) or len(result) != 2:
        raise RuntimeV2Error(
            "invalid_tool_contribution",
            f"{label} contribution requires a two-item prepared tool set",
        )
    raw_tools: object = result[0]
    raw_definitions: object = result[1]
    if (
        not isinstance(raw_tools, Mapping)
        or not isinstance(raw_definitions, Sequence)
        or isinstance(raw_definitions, (str, bytes))
    ):
        raise RuntimeV2Error(
            "invalid_tool_contribution",
            f"{label} contribution received invalid prepared tool collections",
        )

    prepared_tools = cast("Mapping[str, Any]", raw_tools)
    missing = sorted(required_tool_names.difference(prepared_tools))
    if missing:
        raise RuntimeV2Error(
            "missing_prepared_tool_contribution",
            f"{label} contribution is missing prepared tools: {', '.join(missing)}",
        )
    tools = {name: prepared_tools[name] for name in sorted(required_tool_names)}
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(convert_tools(tools)),
    )


def _register_prepared_tool_group_v2(
    context: ContextV2,
    config: Mapping[str, Any],
    *,
    expected_source_id: str,
    label: str,
    required_tool_names: frozenset[str],
) -> ToolContributionDisposerV2:
    source_id = config.get("source_id")
    if source_id != expected_source_id:
        raise ValueError(f"{label} contribution requires source_id {expected_source_id}")
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            f"{label} contribution received an invalid tool catalog",
        )

    def contribution(**kwargs: object) -> ToolSetV2:
        return _prepared_tool_group_v2(
            agent=kwargs["agent"],
            selection_context=kwargs.get("selection_context"),
            label=label,
            required_tool_names=required_tool_names,
        )

    return catalog.register_tools(expected_source_id, contribution)


def _apply_agent_todo_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    return _register_prepared_tool_group_v2(
        context,
        config,
        expected_source_id=AGENT_TODO_TOOLS_SOURCE_V2,
        label="Todo tool",
        required_tool_names=AGENT_TODO_TOOL_NAMES_V2,
    )


def _apply_agent_peer_session_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    return _register_prepared_tool_group_v2(
        context,
        config,
        expected_source_id=AGENT_PEER_SESSION_TOOLS_SOURCE_V2,
        label="Peer-session tool",
        required_tool_names=AGENT_PEER_SESSION_TOOL_NAMES_V2,
    )


def _apply_agent_session_status_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    return _register_prepared_tool_group_v2(
        context,
        config,
        expected_source_id=AGENT_SESSION_STATUS_TOOL_SOURCE_V2,
        label="Session-status tool",
        required_tool_names=AGENT_SESSION_STATUS_TOOL_NAMES_V2,
    )


def _apply_agent_cron_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    return _register_prepared_tool_group_v2(
        context,
        config,
        expected_source_id=AGENT_CRON_TOOL_SOURCE_V2,
        label="Cron tool",
        required_tool_names=AGENT_CRON_TOOL_NAMES_V2,
    )


def builtin_agent_task_session_tool_contribution_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=AGENT_TODO_TOOLS_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_TODO_TOOLS_MODULE_V2),
            apply=_apply_agent_todo_tool_contribution_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_PEER_SESSION_TOOLS_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_PEER_SESSION_TOOLS_MODULE_V2),
            apply=_apply_agent_peer_session_tool_contribution_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_SESSION_STATUS_TOOL_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_SESSION_STATUS_TOOL_MODULE_V2),
            apply=_apply_agent_session_status_tool_contribution_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_CRON_TOOL_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_CRON_TOOL_MODULE_V2),
            apply=_apply_agent_cron_tool_contribution_v2,
        ),
    )


__all__ = [
    "AGENT_CRON_TOOL_MODULE_V2",
    "AGENT_CRON_TOOL_NAMES_V2",
    "AGENT_CRON_TOOL_SOURCE_V2",
    "AGENT_PEER_SESSION_TOOLS_MODULE_V2",
    "AGENT_PEER_SESSION_TOOLS_SOURCE_V2",
    "AGENT_PEER_SESSION_TOOL_NAMES_V2",
    "AGENT_SESSION_STATUS_TOOL_MODULE_V2",
    "AGENT_SESSION_STATUS_TOOL_NAMES_V2",
    "AGENT_SESSION_STATUS_TOOL_SOURCE_V2",
    "AGENT_TODO_TOOLS_MODULE_V2",
    "AGENT_TODO_TOOLS_SOURCE_V2",
    "AGENT_TODO_TOOL_NAMES_V2",
    "builtin_agent_task_session_tool_contribution_definitions_v2",
]
