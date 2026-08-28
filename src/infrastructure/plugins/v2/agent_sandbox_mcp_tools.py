"""Generation-owned contribution for dynamically named sandbox MCP tools."""

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
from .tool_set import (
    PreparedToolProviderV2,
    ToolContributionDisposerV2,
    ToolSetCatalogProtocolV2,
    ToolSetV2,
    normalized_tool_tags_v2,
)

AGENT_SANDBOX_MCP_TOOLS_MODULE_V2 = "builtin://memstack/agent/tool/sandbox-mcp"
AGENT_SANDBOX_MCP_TOOLS_SOURCE_V2 = "builtin-agent-sandbox-mcp-tools"
SANDBOX_MCP_TOOL_REQUIRED_TAGS_V2 = frozenset({"mcp", "sandbox"})


def _agent_sandbox_mcp_tool_set_v2(
    *,
    agent: object,
    selection_context: object | None,
    prepared_tool_provider: PreparedToolProviderV2,
    required_tags: frozenset[str],
) -> ToolSetV2:
    """Select exact Worker-prepared tools declaring the sandbox MCP contract tags."""
    _ = agent, selection_context
    prepared_tools = prepared_tool_provider.tools
    selected_tools = {
        name: tool
        for name, tool in prepared_tools.items()
        if required_tags.issubset(normalized_tool_tags_v2(tool))
    }
    tools = {name: selected_tools[name] for name in sorted(selected_tools)}
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(convert_tools(tools)),
    )


def _apply_agent_sandbox_mcp_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    source_id = config.get("source_id")
    if source_id != AGENT_SANDBOX_MCP_TOOLS_SOURCE_V2:
        raise ValueError(
            "sandbox MCP contribution requires source_id builtin-agent-sandbox-mcp-tools"
        )
    raw_required_tags = config.get("required_tags")
    if not isinstance(raw_required_tags, Sequence) or isinstance(
        raw_required_tags,
        (str, bytes),
    ):
        raise ValueError("sandbox MCP contribution requires required_tags")
    required_tag_items = cast("Sequence[object]", raw_required_tags)
    required_tags = frozenset(
        tag.strip() for tag in required_tag_items if isinstance(tag, str) and tag.strip()
    )
    if (
        len(required_tags) != len(required_tag_items)
        or required_tags != SANDBOX_MCP_TOOL_REQUIRED_TAGS_V2
    ):
        raise ValueError("sandbox MCP contribution requires tags mcp and sandbox")
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "sandbox MCP contribution received an invalid tool catalog",
        )

    def contribution(**kwargs: object) -> ToolSetV2:
        return _agent_sandbox_mcp_tool_set_v2(
            agent=kwargs["agent"],
            selection_context=kwargs.get("selection_context"),
            prepared_tool_provider=cast("PreparedToolProviderV2", kwargs["prepared_tool_provider"]),
            required_tags=required_tags,
        )

    return catalog.register_tools(source_id, contribution)


def builtin_agent_sandbox_mcp_tool_contribution_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_SANDBOX_MCP_TOOLS_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_SANDBOX_MCP_TOOLS_MODULE_V2),
        apply=_apply_agent_sandbox_mcp_tool_contribution_v2,
    )


__all__ = [
    "AGENT_SANDBOX_MCP_TOOLS_MODULE_V2",
    "AGENT_SANDBOX_MCP_TOOLS_SOURCE_V2",
    "SANDBOX_MCP_TOOL_REQUIRED_TAGS_V2",
    "builtin_agent_sandbox_mcp_tool_contribution_definition_v2",
]
