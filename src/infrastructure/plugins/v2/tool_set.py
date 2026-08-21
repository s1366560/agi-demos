"""Generation-scoped tool-set Provider for the v2 runtime spine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2

TOOL_SET_MODULE_V2 = "builtin://memstack/agent/tool-set"
TOOL_SET_RESOLVER_SERVICE_V2 = "service:tool-set-resolver"


@runtime_checkable
class ToolSetResolverProtocolV2(Protocol):
    """Structural contract consumed by generation-scoped tool callers."""

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object | None,
    ) -> tuple[dict[str, Any], list[Any]]: ...


@dataclass(frozen=True, kw_only=True)
class ToolSetResolverV2:
    """Resolve current tools through the agent's generation-safe tool provider."""

    strategy: str

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object | None,
    ) -> tuple[dict[str, Any], list[Any]]:
        get_current_tools = getattr(agent, "_get_current_tools", None)
        if not callable(get_current_tools):
            raise TypeError("agent has no callable _get_current_tools")
        result = get_current_tools(selection_context=selection_context)
        if not isinstance(result, tuple) or len(result) != 2:
            raise TypeError("tool-set provider must return a two-item tuple")
        raw_tools, definitions = result
        if not isinstance(raw_tools, dict) or not isinstance(definitions, list):
            raise TypeError("tool-set provider returned invalid tool collections")
        return raw_tools, definitions


def _apply_tool_set_resolver_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "dynamic-agent-tools":
        raise ValueError("tool-set provider requires strategy dynamic-agent-tools")
    context.provide(
        TOOL_SET_RESOLVER_SERVICE_V2,
        ToolSetResolverV2(strategy=strategy),
        label="tool-set-resolver",
    )


def builtin_tool_set_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=TOOL_SET_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TOOL_SET_MODULE_V2),
        apply=_apply_tool_set_resolver_v2,
    )


__all__ = [
    "TOOL_SET_MODULE_V2",
    "TOOL_SET_RESOLVER_SERVICE_V2",
    "ToolSetResolverProtocolV2",
    "ToolSetResolverV2",
    "builtin_tool_set_definition_v2",
]
