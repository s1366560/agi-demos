"""Generation-owned tool contribution catalog for the v2 runtime spine."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TOOL_SET_MODULE_V2 = "builtin://memstack/agent/tool-set"
TOOL_SET_CATALOG_SERVICE_V2 = "service:tool-set-catalog"
TOOL_SET_RESOLVER_SERVICE_V2 = "service:tool-set-resolver"
OPERATION_TOOL_SET_CATALOG_SERVICE_V2 = "service:operation.tool-set-contributions"

type ToolContributionDisposerV2 = Callable[[], None | Awaitable[None]]
type ToolContributionV2 = Callable[..., object]


def normalized_tool_tags_v2(tool: object) -> frozenset[str]:
    """Return validated static source tags declared by one prepared tool."""
    raw_tags: object = getattr(tool, "tags", frozenset())
    if not isinstance(raw_tags, (set, frozenset, tuple, list)):
        return frozenset()
    return frozenset(tag.strip() for tag in raw_tags if isinstance(tag, str) and tag.strip())


@dataclass(frozen=True, kw_only=True)
class ToolSetV2:
    """Immutable complete tool view resolved from one pinned generation."""

    tools: Mapping[str, Any]
    definitions: tuple[Any, ...]
    selection_trace: tuple[Any, ...] = ()


@runtime_checkable
class ToolSetContributionCatalogProtocolV2(Protocol):
    """Ordered contribution catalog owned by one generation or operation."""

    def register_tools(
        self,
        source_id: str,
        contribution: ToolContributionV2,
    ) -> ToolContributionDisposerV2: ...

    def contributions(self) -> tuple[tuple[str, ToolContributionV2], ...]: ...


@runtime_checkable
class ToolSetCatalogProtocolV2(ToolSetContributionCatalogProtocolV2, Protocol):
    """Generation catalog that merges an optional operation overlay."""

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object | None,
        operation_catalog: ToolSetContributionCatalogProtocolV2 | None = None,
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

    def contributions(self) -> tuple[tuple[str, ToolContributionV2], ...]:
        """Snapshot ordered sources without exposing the mutable registry."""
        return tuple(self._sources.items())

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object | None,
        operation_catalog: ToolSetContributionCatalogProtocolV2 | None = None,
    ) -> ToolSetV2:
        resolved_tools: dict[str, Any] = {}
        definitions: list[Any] = []
        source_by_name: dict[str, str] = {}
        source_ids: set[str] = set()
        catalogs: tuple[ToolSetContributionCatalogProtocolV2, ...] = (
            (self,)
            if operation_catalog is None
            else (
                self,
                operation_catalog,
            )
        )
        for source_id, contribution in (
            item for catalog in catalogs for item in catalog.contributions()
        ):
            if source_id in source_ids:
                raise RuntimeV2Error(
                    "tool_contribution_source_conflict",
                    f"tool source {source_id} exists in generation and operation catalogs",
                )
            source_ids.add(source_id)
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
        resolved_tools, definitions, selection_trace = _select_complete_tool_set_v2(
            agent=agent,
            selection_context=selection_context,
            tools=resolved_tools,
            definitions=definitions,
        )
        return ToolSetV2(
            tools=MappingProxyType(resolved_tools),
            definitions=tuple(definitions),
            selection_trace=selection_trace,
        )


@runtime_checkable
class ToolSetResolverProtocolV2(Protocol):
    """Structural contract consumed by generation-scoped tool callers."""

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object | None,
        operation_catalog: ToolSetContributionCatalogProtocolV2 | None = None,
    ) -> ToolSetV2: ...


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
        operation_catalog: ToolSetContributionCatalogProtocolV2 | None = None,
    ) -> ToolSetV2:
        return self.catalog.resolve(
            agent=agent,
            selection_context=selection_context,
            operation_catalog=operation_catalog,
        )


def bind_operation_tool_set_catalog_v2(
    operation: OperationContextV2 | None = None,
) -> ToolSetContributionCatalogProtocolV2:
    """Bind one disposable contribution catalog to the current operation."""
    if operation is None:
        from .boundary import current_operation_context_v2

        operation = current_operation_context_v2()
    try:
        existing = operation.require(OPERATION_TOOL_SET_CATALOG_SERVICE_V2)
    except RuntimeV2Error as exc:
        if exc.code != "missing_service":
            raise
        catalog = ToolSetCatalogV2()
        _ = operation.provide(
            OPERATION_TOOL_SET_CATALOG_SERVICE_V2,
            catalog,
            label="operation-tool-set-catalog",
        )
        return catalog
    if not isinstance(existing, ToolSetContributionCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_operation_tool_set_catalog",
            "operation tool contribution catalog has an invalid implementation",
        )
    return existing


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


def _select_complete_tool_set_v2(
    *,
    agent: object,
    selection_context: object | None,
    tools: dict[str, Any],
    definitions: list[Any],
) -> tuple[dict[str, Any], list[Any], tuple[Any, ...]]:
    """Run the agent-owned selector once after all V2 contributions are merged."""
    if selection_context is None:
        return tools, definitions, ()
    pipeline = getattr(agent, "_tool_selection_pipeline", None)
    if pipeline is None:
        return tools, definitions, ()
    select_with_trace = getattr(pipeline, "select_with_trace", None)
    if not callable(select_with_trace):
        raise RuntimeV2Error(
            "invalid_tool_selection_pipeline",
            "agent tool-selection pipeline has no callable select_with_trace",
        )
    result = select_with_trace(dict(tools), selection_context)
    selected_tools = getattr(result, "tools", None)
    trace = getattr(result, "trace", None)
    if not isinstance(selected_tools, Mapping) or trace is None:
        raise RuntimeV2Error(
            "invalid_tool_selection_result",
            "agent tool-selection pipeline returned an invalid result",
        )
    normalized_tools: dict[str, Any] = {}
    for name, tool in selected_tools.items():
        if not isinstance(name, str) or name not in tools or tools[name] is not tool:
            raise RuntimeV2Error(
                "invalid_tool_selection_result",
                "agent tool-selection pipeline returned an unknown tool",
            )
        normalized_tools[name] = tool
    from src.infrastructure.agent.core.tool_converter import convert_tools

    return normalized_tools, list(convert_tools(normalized_tools)), tuple(trace)


def restrict_tool_set_v2(
    tool_set: ToolSetV2,
    definitions: Sequence[Any],
    *,
    selection_trace: Sequence[Any] | None = None,
) -> ToolSetV2:
    """Return an immutable name-synchronized subset of one resolved ToolSet."""
    normalized_definitions = tuple(definitions)
    names: list[str] = []
    for definition in normalized_definitions:
        name = getattr(definition, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise RuntimeV2Error(
                "invalid_tool_definition",
                "turn ToolSet contains a definition without a valid name",
            )
        normalized_name = name.strip()
        if normalized_name in names:
            raise RuntimeV2Error(
                "duplicate_tool_definition",
                f"turn ToolSet contains duplicate definition {normalized_name}",
            )
        if normalized_name not in tool_set.tools:
            raise RuntimeV2Error(
                "tool_definition_not_provided",
                f"turn ToolSet definition {normalized_name} has no provided tool",
            )
        names.append(normalized_name)
    return ToolSetV2(
        tools=MappingProxyType({name: tool_set.tools[name] for name in names}),
        definitions=normalized_definitions,
        selection_trace=tuple(
            tool_set.selection_trace if selection_trace is None else selection_trace
        ),
    )


def builtin_tool_set_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=TOOL_SET_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TOOL_SET_MODULE_V2),
        apply=_apply_tool_set_resolver_v2,
    )


__all__ = [
    "OPERATION_TOOL_SET_CATALOG_SERVICE_V2",
    "TOOL_SET_CATALOG_SERVICE_V2",
    "TOOL_SET_MODULE_V2",
    "TOOL_SET_RESOLVER_SERVICE_V2",
    "ToolSetCatalogProtocolV2",
    "ToolSetCatalogV2",
    "ToolSetContributionCatalogProtocolV2",
    "ToolSetResolverProtocolV2",
    "ToolSetResolverV2",
    "ToolSetV2",
    "bind_operation_tool_set_catalog_v2",
    "builtin_tool_set_definition_v2",
    "restrict_tool_set_v2",
]
