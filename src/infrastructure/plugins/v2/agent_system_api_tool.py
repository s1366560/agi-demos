"""Generation-owned contribution for the Worker-prepared system API tool."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from src.infrastructure.agent.core.tool_converter import convert_tools

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .tool_set import (
    PreparedToolProviderV2,
    ToolContributionDisposerV2,
    ToolSetCatalogProtocolV2,
    ToolSetV2,
)

AGENT_SYSTEM_API_TOOL_MODULE_V2 = "builtin://memstack/agent/tool/system-api"
AGENT_SYSTEM_API_TOOL_SOURCE_V2 = "builtin-agent-system-api-tool"
AGENT_SYSTEM_API_TOOL_NAME_V2 = "system_api"


def _agent_system_api_tool_set_v2(
    *,
    agent: object,
    selection_context: object | None,
    prepared_tool_provider: PreparedToolProviderV2,
) -> ToolSetV2:
    """Select the exact system API ToolInfo prepared for this Agent instance."""
    _ = agent, selection_context
    prepared_tools = prepared_tool_provider.tools
    if AGENT_SYSTEM_API_TOOL_NAME_V2 not in prepared_tools:
        raise RuntimeV2Error(
            "missing_prepared_tool_contribution",
            "system API tool contribution is missing prepared tool: system_api",
        )
    tools = {AGENT_SYSTEM_API_TOOL_NAME_V2: prepared_tools[AGENT_SYSTEM_API_TOOL_NAME_V2]}
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(convert_tools(tools)),
    )


def _apply_agent_system_api_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    source_id = config.get("source_id")
    if source_id != AGENT_SYSTEM_API_TOOL_SOURCE_V2:
        raise ValueError("system API contribution requires source_id builtin-agent-system-api-tool")
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Agent system API contribution received an invalid tool catalog",
        )
    return catalog.register_tools(source_id, _agent_system_api_tool_set_v2)


def builtin_agent_system_api_tool_contribution_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_SYSTEM_API_TOOL_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_SYSTEM_API_TOOL_MODULE_V2),
        apply=_apply_agent_system_api_tool_contribution_v2,
    )


__all__ = [
    "AGENT_SYSTEM_API_TOOL_MODULE_V2",
    "AGENT_SYSTEM_API_TOOL_NAME_V2",
    "AGENT_SYSTEM_API_TOOL_SOURCE_V2",
    "builtin_agent_system_api_tool_contribution_definition_v2",
]
