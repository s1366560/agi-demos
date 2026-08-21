"""Generation-owned tool contribution catalog for the v2 runtime spine."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TOOL_SET_MODULE_V2 = "builtin://memstack/agent/tool-set"
TOOL_CONTRIBUTION_MODULE_V2 = "builtin://memstack/agent/tool-contribution"
TOOL_SET_CATALOG_SERVICE_V2 = "service:tool-set-catalog"
TOOL_SET_RESOLVER_SERVICE_V2 = "service:tool-set-resolver"

type ToolContributionDisposerV2 = Callable[[], None | Awaitable[None]]
type ToolContributionV2 = Callable[..., object]


@dataclass(frozen=True, kw_only=True)
class ToolSetV2:
    """Immutable complete tool view resolved from one pinned generation."""

    tools: Mapping[str, Any]
    definitions: tuple[Any, ...]


@runtime_checkable
class ToolSetCatalogProtocolV2(Protocol):
    """Mutable ordered contribution catalog owned by one staged generation."""

    def register_tools(
        self,
        source_id: str,
        contribution: ToolContributionV2,
    ) -> ToolContributionDisposerV2: ...

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object | None,
    ) -> ToolSetV2: ...


class ToolSetCatalogV2:
    """Resolve only tool sources registered by active Profile entries."""

    def __init__(self) -> None:
        super().__init__()
        self._sources: dict[str, ToolContributionV2] = {}

    def register_tools(
        self,
        source_id: str,
        contribution: ToolContributionV2,
    ) -> ToolContributionDisposerV2:
        normalized_source_id = source_id.strip()
        if not normalized_source_id or not callable(contribution):
            raise RuntimeV2Error(
                "invalid_tool_contribution",
                "tool contribution requires a non-empty source_id and callable provider",
            )
        if normalized_source_id in self._sources:
            raise RuntimeV2Error(
                "tool_contribution_source_conflict",
                f"tool source {normalized_source_id} already has a contribution",
            )
        self._sources[normalized_source_id] = contribution

        async def dispose() -> None:
            if self._sources.get(normalized_source_id) is contribution:
                _ = self._sources.pop(normalized_source_id, None)

        return dispose

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object | None,
    ) -> ToolSetV2:
        resolved_tools: dict[str, Any] = {}
        definitions: list[Any] = []
        source_by_name: dict[str, str] = {}
        for source_id, contribution in self._sources.items():
            raw_result: object = contribution(
                agent=agent,
                selection_context=selection_context,
            )
            if inspect.isawaitable(raw_result):
                if inspect.iscoroutine(raw_result):
                    raw_result.close()
                raise RuntimeV2Error(
                    "invalid_tool_contribution",
                    f"tool source {source_id} returned an awaitable",
                )
            if not isinstance(raw_result, ToolSetV2):
                raise RuntimeV2Error(
                    "invalid_tool_contribution",
                    f"tool source {source_id} returned an invalid tool set",
                )
            raw_tools: object = raw_result.tools
            raw_definitions: object = raw_result.definitions
            if (
                not isinstance(raw_tools, Mapping)
                or not isinstance(raw_definitions, Sequence)
                or isinstance(raw_definitions, (str, bytes))
            ):
                raise RuntimeV2Error(
                    "invalid_tool_contribution",
                    f"tool source {source_id} returned invalid tool collections",
                )
            tools = cast("Mapping[object, Any]", raw_tools)
            contribution_definitions = raw_definitions
            for tool_name, tool in tools.items():
                if not isinstance(tool_name, str) or not tool_name.strip():
                    raise RuntimeV2Error(
                        "invalid_tool_contribution",
                        f"tool source {source_id} returned an invalid tool name",
                    )
                normalized_tool_name = tool_name.strip().casefold()
                previous_source = source_by_name.get(normalized_tool_name)
                if previous_source is not None:
                    raise RuntimeV2Error(
                        "tool_contribution_conflict",
                        f"tool {tool_name} duplicate sources: {previous_source}, {source_id}",
                    )
                source_by_name[normalized_tool_name] = source_id
                resolved_tools[tool_name] = tool
            definitions.extend(contribution_definitions)
        return ToolSetV2(
            tools=MappingProxyType(resolved_tools),
            definitions=tuple(definitions),
        )


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
    """Resolve the complete tool set from one generation-owned catalog."""

    strategy: str
    catalog: ToolSetCatalogProtocolV2

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object | None,
    ) -> tuple[dict[str, Any], list[Any]]:
        result = self.catalog.resolve(agent=agent, selection_context=selection_context)
        return dict(result.tools), list(result.definitions)


def _apply_tool_set_resolver_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "ordered-contributions":
        raise ValueError("tool-set provider requires strategy ordered-contributions")
    catalog = ToolSetCatalogV2()
    _ = context.provide(
        TOOL_SET_CATALOG_SERVICE_V2,
        catalog,
        label="tool-set-catalog",
    )
    _ = context.provide(
        TOOL_SET_RESOLVER_SERVICE_V2,
        ToolSetResolverV2(strategy=strategy, catalog=catalog),
        label="tool-set-resolver",
    )


def _agent_owned_tools_v2(
    *,
    agent: object,
    selection_context: object | None,
) -> ToolSetV2:
    get_current_tools = getattr(agent, "_get_current_tools", None)
    if not callable(get_current_tools):
        raise RuntimeV2Error(
            "invalid_tool_contribution",
            "agent-owned tool contribution requires callable _get_current_tools",
        )
    result: object = get_current_tools(selection_context=selection_context)
    if not isinstance(result, tuple) or len(result) != 2:
        raise RuntimeV2Error(
            "invalid_tool_contribution",
            "agent-owned tool contribution must return a two-item tuple",
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
            "agent-owned tool contribution returned invalid tool collections",
        )
    tools = cast("Mapping[str, Any]", raw_tools)
    definitions = raw_definitions
    return ToolSetV2(tools=tools, definitions=tuple(definitions))


def _apply_tool_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ToolContributionDisposerV2:
    if config.get("strategy") != "agent-runtime-state":
        raise ValueError("tool contribution requires strategy agent-runtime-state")
    source_id = config.get("source_id")
    if source_id != "agent-owned-tools":
        raise ValueError("tool contribution requires source_id agent-owned-tools")
    catalog = context.require("catalog")
    if not isinstance(catalog, ToolSetCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "tool-set catalog service has an invalid implementation",
        )
    return catalog.register_tools(source_id, _agent_owned_tools_v2)


def builtin_tool_set_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=TOOL_SET_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TOOL_SET_MODULE_V2),
        apply=_apply_tool_set_resolver_v2,
    )


def builtin_tool_contribution_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=TOOL_CONTRIBUTION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TOOL_CONTRIBUTION_MODULE_V2),
        apply=_apply_tool_contribution_v2,
    )


__all__ = [
    "TOOL_CONTRIBUTION_MODULE_V2",
    "TOOL_SET_CATALOG_SERVICE_V2",
    "TOOL_SET_MODULE_V2",
    "TOOL_SET_RESOLVER_SERVICE_V2",
    "ToolSetCatalogProtocolV2",
    "ToolSetCatalogV2",
    "ToolSetResolverProtocolV2",
    "ToolSetResolverV2",
    "ToolSetV2",
    "builtin_tool_contribution_definition_v2",
    "builtin_tool_set_definition_v2",
]
