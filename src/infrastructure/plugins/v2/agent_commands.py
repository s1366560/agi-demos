"""Generation-owned slash-command Provider and contribution catalog."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol, override, runtime_checkable

from src.infrastructure.agent.commands.builtins import register_builtin_commands
from src.infrastructure.agent.commands.interceptor import CommandInterceptor
from src.infrastructure.agent.commands.registry import CommandRegistry
from src.infrastructure.agent.commands.types import (
    CommandCategory,
    CommandDefinition,
    CommandResult,
    CommandScope,
)

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

AGENT_COMMAND_CATALOG_MODULE_V2 = "builtin://memstack/agent/command-catalog"
AGENT_COMMAND_CONTRIBUTION_MODULE_V2 = "builtin://memstack/agent/command-contribution"
AGENT_COMMAND_CATALOG_SERVICE_V2 = "service:agent-command-catalog"

type AgentCommandDisposerV2 = Callable[[], None | Awaitable[None]]


@runtime_checkable
class AgentCommandCatalogProtocolV2(Protocol):
    """Ordered command sources owned by one staged generation."""

    def register(
        self,
        source_id: str,
        definitions: Sequence[CommandDefinition],
    ) -> AgentCommandDisposerV2: ...

    def interceptor(self) -> CommandInterceptor: ...

    def list_commands(
        self,
        category: CommandCategory | None = None,
        scope: CommandScope | None = None,
        include_hidden: bool = False,
    ) -> list[CommandDefinition]: ...


class AgentCommandCatalogV2:
    """Mutable activation catalog exposed as an immutable runtime registry view."""

    def __init__(self) -> None:
        super().__init__()
        self._sources: dict[str, tuple[CommandDefinition, ...]] = {}
        self._registry = CommandRegistry()
        self._interceptor = CommandInterceptor(self._registry)

    def register(
        self,
        source_id: str,
        definitions: Sequence[CommandDefinition],
    ) -> AgentCommandDisposerV2:
        normalized_source_id = source_id.strip()
        if not normalized_source_id:
            raise RuntimeV2Error(
                "invalid_agent_command_contribution",
                "agent command contribution requires a non-empty source_id",
            )
        if normalized_source_id in self._sources:
            raise RuntimeV2Error(
                "agent_command_source_conflict",
                f"agent command source {normalized_source_id} is already registered",
            )
        normalized_definitions = tuple(definitions)
        candidate_sources = {**self._sources, normalized_source_id: normalized_definitions}
        candidate_registry = self._build_registry(candidate_sources)
        self._sources = candidate_sources
        self._replace_registry(candidate_registry)

        async def dispose() -> None:
            if self._sources.get(normalized_source_id) is not normalized_definitions:
                return
            remaining_sources = dict(self._sources)
            _ = remaining_sources.pop(normalized_source_id, None)
            remaining_registry = self._build_registry(remaining_sources)
            self._sources = remaining_sources
            self._replace_registry(remaining_registry)

        return dispose

    @staticmethod
    def _build_registry(
        sources: Mapping[str, Sequence[CommandDefinition]],
    ) -> CommandRegistry:
        registry = CommandRegistry()
        try:
            for definitions in sources.values():
                for definition in definitions:
                    registry.register(definition)
        except ValueError as exc:
            raise RuntimeV2Error(
                "agent_command_contribution_conflict",
                f"agent command contributions conflict: {exc}",
            ) from exc
        return registry

    def _replace_registry(self, registry: CommandRegistry) -> None:
        self._registry = registry
        self._interceptor = CommandInterceptor(registry)

    def interceptor(self) -> CommandInterceptor:
        """Return the exact combined interceptor for the active generation."""
        return self._interceptor

    def list_commands(
        self,
        category: CommandCategory | None = None,
        scope: CommandScope | None = None,
        include_hidden: bool = False,
    ) -> list[CommandDefinition]:
        """List definitions contributed to the active generation."""
        return self._registry.list_commands(
            category=category,
            scope=scope,
            include_hidden=include_hidden,
        )


def current_agent_command_catalog_v2() -> AgentCommandCatalogProtocolV2:
    """Resolve and validate the command catalog from the pinned operation."""
    from .boundary import current_operation_context_v2

    catalog = current_operation_context_v2().require(AGENT_COMMAND_CATALOG_SERVICE_V2)
    return _validated_agent_command_catalog_v2(catalog)


def current_generation_agent_command_catalog_v2() -> AgentCommandCatalogProtocolV2:
    """Resolve the command catalog from an HTTP/WebSocket generation boundary."""
    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

    from .boundary import current_generation_v2

    catalog = current_generation_v2().resolve(
        AGENT_COMMAND_CATALOG_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    return _validated_agent_command_catalog_v2(catalog)


def _validated_agent_command_catalog_v2(
    catalog: object,
) -> AgentCommandCatalogProtocolV2:
    if not isinstance(catalog, AgentCommandCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_command_catalog",
            "service:agent-command-catalog has an invalid implementation",
        )
    return catalog


class PinnedCommandInterceptorV2(CommandInterceptor):
    """Resolve command interception from the operation's immutable generation."""

    def __init__(self) -> None:
        super().__init__(CommandRegistry())

    @override
    async def try_intercept(
        self,
        message: str,
        context: dict[str, Any],
    ) -> CommandResult | None:
        return (
            await current_agent_command_catalog_v2()
            .interceptor()
            .try_intercept(
                message,
                context,
            )
        )

    @override
    def is_command(self, message: str) -> bool:
        return current_agent_command_catalog_v2().interceptor().is_command(message)


def _apply_agent_command_catalog_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "ordered-contributions":
        raise ValueError("agent command catalog requires strategy ordered-contributions")
    _ = context.provide(
        AGENT_COMMAND_CATALOG_SERVICE_V2,
        AgentCommandCatalogV2(),
        label="agent-command-catalog",
    )


def _apply_builtin_agent_command_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> AgentCommandDisposerV2:
    if config.get("strategy") != "builtin-commands":
        raise ValueError("builtin command contribution requires strategy builtin-commands")
    source_id = config.get("source_id")
    if source_id != "builtin-agent-commands":
        raise ValueError("builtin command contribution requires source_id builtin-agent-commands")
    catalog = context.require("catalog")
    if not isinstance(catalog, AgentCommandCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "agent-command catalog service has an invalid implementation",
        )
    registry = CommandRegistry()
    register_builtin_commands(registry)
    return catalog.register(
        source_id,
        registry.list_commands(include_hidden=True),
    )


def builtin_agent_command_catalog_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_COMMAND_CATALOG_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_COMMAND_CATALOG_MODULE_V2),
        apply=_apply_agent_command_catalog_v2,
    )


def builtin_agent_command_contribution_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_COMMAND_CONTRIBUTION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_COMMAND_CONTRIBUTION_MODULE_V2),
        apply=_apply_builtin_agent_command_contribution_v2,
    )


__all__ = [
    "AGENT_COMMAND_CATALOG_MODULE_V2",
    "AGENT_COMMAND_CATALOG_SERVICE_V2",
    "AGENT_COMMAND_CONTRIBUTION_MODULE_V2",
    "AgentCommandCatalogProtocolV2",
    "AgentCommandCatalogV2",
    "PinnedCommandInterceptorV2",
    "builtin_agent_command_catalog_definition_v2",
    "builtin_agent_command_contribution_definition_v2",
    "current_agent_command_catalog_v2",
    "current_generation_agent_command_catalog_v2",
]
