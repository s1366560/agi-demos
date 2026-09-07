"""Generation-owned Agent orchestration tool contribution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.tools.agent_definition_tool import agent_definition_manage_tool
from src.infrastructure.agent.tools.agent_history import agent_history_tool
from src.infrastructure.agent.tools.agent_list import agent_list_tool
from src.infrastructure.agent.tools.agent_send import agent_send_tool
from src.infrastructure.agent.tools.agent_sessions import agent_sessions_tool
from src.infrastructure.agent.tools.agent_spawn import agent_spawn_tool
from src.infrastructure.agent.tools.agent_stop import agent_stop_tool
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.workspace_clarification import (
    workspace_request_clarification_tool,
    workspace_respond_clarification_tool,
)
from src.infrastructure.agent.tools.workspace_health_verdict import (
    workspace_health_verdict_tool,
)
from src.infrastructure.agent.tools.workspace_leader_wtp import (
    workspace_assign_task_tool,
    workspace_cancel_task_tool,
)
from src.infrastructure.agent.tools.workspace_wtp import (
    workspace_report_blocked_tool,
    workspace_report_complete_tool,
    workspace_report_progress_tool,
)
from src.infrastructure.agent.workspace.wtp_publisher_runtime import (
    WorkspaceWtpPublisherProtocolV2,
    bind_workspace_wtp_publisher_v2,
)

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .tool_set import ToolContributionDisposerV2, ToolSetCatalogProtocolV2, ToolSetV2

AGENT_ORCHESTRATION_TOOLS_MODULE_V2 = "builtin://memstack/agent/tool/orchestration"
AGENT_ORCHESTRATION_TOOLS_SOURCE_V2 = "builtin-agent-orchestration-tools"

_AGENT_ORCHESTRATION_TOOLS_V2 = (
    agent_spawn_tool,
    agent_list_tool,
    agent_send_tool,
    agent_sessions_tool,
    agent_history_tool,
    agent_stop_tool,
    agent_definition_manage_tool,
    workspace_report_progress_tool,
    workspace_report_complete_tool,
    workspace_report_blocked_tool,
    workspace_request_clarification_tool,
    workspace_respond_clarification_tool,
    workspace_assign_task_tool,
    workspace_cancel_task_tool,
    workspace_health_verdict_tool,
)
_WORKSPACE_WTP_TOOL_NAMES_V2 = frozenset(
    {
        "workspace_assign_task",
        "workspace_cancel_task",
        "workspace_report_blocked",
        "workspace_report_complete",
        "workspace_report_progress",
    }
)


def _bind_workspace_wtp_tool_v2(
    tool: ToolInfo,
    publisher: WorkspaceWtpPublisherProtocolV2,
) -> ToolInfo:
    async def execute(ctx: ToolContext, **kwargs: object) -> object:
        with bind_workspace_wtp_publisher_v2(publisher):
            return await tool.execute(ctx, **kwargs)

    return replace(tool, execute=execute)


def _agent_orchestration_tool_set_v2(
    *,
    publisher: WorkspaceWtpPublisherProtocolV2,
    **_kwargs: object,
) -> ToolSetV2:
    tools = {
        tool.name: (
            _bind_workspace_wtp_tool_v2(tool, publisher)
            if tool.name in _WORKSPACE_WTP_TOOL_NAMES_V2
            else tool
        )
        for tool in _AGENT_ORCHESTRATION_TOOLS_V2
    }
    if len(tools) != len(_AGENT_ORCHESTRATION_TOOLS_V2):
        raise RuntimeV2Error(
            "tool_contribution_conflict",
            "Agent orchestration tool contribution contains duplicate names",
        )
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(convert_tools(tools)),
    )


def _apply_agent_orchestration_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    source_id = config.get("source_id")
    if source_id != AGENT_ORCHESTRATION_TOOLS_SOURCE_V2:
        raise ValueError(
            "Agent orchestration tool contribution requires source_id "
            "builtin-agent-orchestration-tools"
        )
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Agent orchestration tool contribution received an invalid tool catalog",
        )
    publisher = context.require("publisher")
    if not isinstance(publisher, WorkspaceWtpPublisherProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Agent orchestration tool contribution received an invalid WTP publisher",
        )

    def contribution(**kwargs: object) -> ToolSetV2:
        return _agent_orchestration_tool_set_v2(publisher=publisher, **kwargs)

    return catalog.register_tools(source_id, contribution)


def builtin_agent_orchestration_tool_contribution_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_ORCHESTRATION_TOOLS_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_ORCHESTRATION_TOOLS_MODULE_V2),
        apply=_apply_agent_orchestration_tool_contribution_v2,
    )


__all__ = [
    "AGENT_ORCHESTRATION_TOOLS_MODULE_V2",
    "AGENT_ORCHESTRATION_TOOLS_SOURCE_V2",
    "builtin_agent_orchestration_tool_contribution_definition_v2",
]
