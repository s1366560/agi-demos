"""Generation-owned contribution for dynamically named custom tools."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, cast

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
    normalized_tool_tags_v2,
)

AGENT_CUSTOM_TOOLS_MODULE_V2 = "builtin://memstack/agent/tool/custom"
AGENT_CUSTOM_TOOLS_SOURCE_V2 = "builtin-agent-custom-tools"
CUSTOM_TOOL_SOURCE_TAG_V2 = "custom"


def _agent_custom_tool_set_v2(
    *,
    agent: object,
    selection_context: object | None,
    prepared_tool_provider: PreparedToolProviderV2,
    source_tag: str,
    required_tool: str,
) -> ToolSetV2:
    """Select exact custom ToolInfos prepared for this Agent instance."""
    _ = agent, selection_context
    prepared_tools = prepared_tool_provider.tools
    tools = {
        name: tool
        for name, tool in prepared_tools.items()
        if source_tag in normalized_tool_tags_v2(tool)
    }
    if required_tool not in tools:
        raise RuntimeV2Error(
            "missing_prepared_tool_contribution",
            f"custom tool contribution is missing prepared tool: {required_tool}",
        )
    ordered_tools = {name: tools[name] for name in sorted(tools)}
    return ToolSetV2(
        tools=MappingProxyType(ordered_tools),
        definitions=tuple(convert_tools(ordered_tools)),
    )


def _apply_agent_custom_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    source_id = config.get("source_id")
    source_tag = config.get("source_tag")
    required_tool = config.get("required_tool")
    if source_id != AGENT_CUSTOM_TOOLS_SOURCE_V2:
        raise ValueError("custom contribution requires source_id builtin-agent-custom-tools")
    if source_tag != CUSTOM_TOOL_SOURCE_TAG_V2:
        raise ValueError("custom contribution requires source_tag custom")
    if required_tool != "custom_tools_status":
        raise ValueError("custom contribution requires custom_tools_status")
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Agent custom contribution received an invalid tool catalog",
        )

    def contribution(**kwargs: object) -> ToolSetV2:
        return _agent_custom_tool_set_v2(
            agent=kwargs["agent"],
            selection_context=kwargs.get("selection_context"),
            prepared_tool_provider=cast("PreparedToolProviderV2", kwargs["prepared_tool_provider"]),
            source_tag=source_tag,
            required_tool=required_tool,
        )

    return catalog.register_tools(source_id, contribution)


def builtin_agent_custom_tool_contribution_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_CUSTOM_TOOLS_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_CUSTOM_TOOLS_MODULE_V2),
        apply=_apply_agent_custom_tool_contribution_v2,
    )


__all__ = [
    "AGENT_CUSTOM_TOOLS_MODULE_V2",
    "AGENT_CUSTOM_TOOLS_SOURCE_V2",
    "CUSTOM_TOOL_SOURCE_TAG_V2",
    "builtin_agent_custom_tool_contribution_definition_v2",
]
