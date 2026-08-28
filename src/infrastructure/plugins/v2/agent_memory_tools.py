"""Generation-owned contribution for Worker-prepared memory tools."""

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

AGENT_MEMORY_TOOLS_MODULE_V2 = "builtin://memstack/agent/tool/memory"
AGENT_MEMORY_TOOLS_SOURCE_V2 = "builtin-agent-memory-tools"
AGENT_MEMORY_TOOL_NAMES_V2 = frozenset(
    {
        "memory_search",
        "memory_get",
        "memory_create",
        "memory_update",
        "memory_delete",
    }
)


def _agent_memory_tool_set_v2(
    *,
    agent: object,
    selection_context: object | None,
    prepared_tool_provider: PreparedToolProviderV2,
) -> ToolSetV2:
    """Select the exact memory ToolInfos prepared for this Agent instance."""
    _ = agent, selection_context
    prepared_tools = prepared_tool_provider.tools
    missing = sorted(AGENT_MEMORY_TOOL_NAMES_V2.difference(prepared_tools))
    if missing:
        raise RuntimeV2Error(
            "missing_prepared_tool_contribution",
            f"memory tool contribution is missing prepared tools: {', '.join(missing)}",
        )
    tools = {name: prepared_tools[name] for name in sorted(AGENT_MEMORY_TOOL_NAMES_V2)}
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(convert_tools(tools)),
    )


def _apply_agent_memory_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    source_id = config.get("source_id")
    if source_id != AGENT_MEMORY_TOOLS_SOURCE_V2:
        raise ValueError(
            "Agent memory tool contribution requires source_id builtin-agent-memory-tools"
        )
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Agent memory tool contribution received an invalid tool catalog",
        )
    return catalog.register_tools(source_id, _agent_memory_tool_set_v2)


def builtin_agent_memory_tool_contribution_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_MEMORY_TOOLS_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_MEMORY_TOOLS_MODULE_V2),
        apply=_apply_agent_memory_tool_contribution_v2,
    )


__all__ = [
    "AGENT_MEMORY_TOOLS_MODULE_V2",
    "AGENT_MEMORY_TOOLS_SOURCE_V2",
    "AGENT_MEMORY_TOOL_NAMES_V2",
    "builtin_agent_memory_tool_contribution_definition_v2",
]
