"""Generation-owned contribution for Worker-prepared model-awareness tools."""

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

AGENT_MODEL_AWARENESS_TOOLS_MODULE_V2 = "builtin://memstack/agent/tool/model-awareness"
AGENT_MODEL_AWARENESS_TOOLS_SOURCE_V2 = "builtin-agent-model-awareness-tools"
AGENT_MODEL_AWARENESS_TOOL_NAMES_V2 = frozenset({"list_available_models", "switch_model_next_turn"})


def _agent_model_awareness_tool_set_v2(
    *,
    agent: object,
    selection_context: object | None,
) -> ToolSetV2:
    """Select exact model-awareness ToolInfos prepared for this Agent instance."""
    get_current_tools = getattr(agent, "_get_current_tools", None)
    if not callable(get_current_tools):
        raise RuntimeV2Error(
            "invalid_tool_contribution",
            "model-awareness tool contribution requires callable _get_current_tools",
        )
    _ = selection_context
    result: object = get_current_tools(selection_context=None)
    if not isinstance(result, tuple) or len(result) != 2:
        raise RuntimeV2Error(
            "invalid_tool_contribution",
            "model-awareness tool contribution requires a two-item prepared tool set",
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
            "model-awareness tool contribution received invalid prepared tool collections",
        )

    prepared_tools = cast("Mapping[str, Any]", raw_tools)
    missing = sorted(AGENT_MODEL_AWARENESS_TOOL_NAMES_V2.difference(prepared_tools))
    if missing:
        raise RuntimeV2Error(
            "missing_prepared_tool_contribution",
            f"model-awareness tool contribution is missing prepared tools: {', '.join(missing)}",
        )
    tools = {name: prepared_tools[name] for name in sorted(AGENT_MODEL_AWARENESS_TOOL_NAMES_V2)}
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(convert_tools(tools)),
    )


def _apply_agent_model_awareness_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    source_id = config.get("source_id")
    if source_id != AGENT_MODEL_AWARENESS_TOOLS_SOURCE_V2:
        raise ValueError(
            "model-awareness contribution requires source_id builtin-agent-model-awareness-tools"
        )
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "Agent model-awareness tool contribution received an invalid tool catalog",
        )
    return catalog.register_tools(source_id, _agent_model_awareness_tool_set_v2)


def builtin_agent_model_awareness_tool_contribution_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_MODEL_AWARENESS_TOOLS_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_MODEL_AWARENESS_TOOLS_MODULE_V2),
        apply=_apply_agent_model_awareness_tool_contribution_v2,
    )


__all__ = [
    "AGENT_MODEL_AWARENESS_TOOLS_MODULE_V2",
    "AGENT_MODEL_AWARENESS_TOOLS_SOURCE_V2",
    "AGENT_MODEL_AWARENESS_TOOL_NAMES_V2",
    "builtin_agent_model_awareness_tool_contribution_definition_v2",
]
