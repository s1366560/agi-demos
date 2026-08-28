"""Generation-scoped agent-definition Provider for the v2 runtime spine."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_ALL_ACCESS_ID,
    BUILTIN_SISYPHUS_ID,
    BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    BUILTIN_WORKSPACE_PLANNER_ID,
    BUILTIN_WORKSPACE_SUPERVISOR_ID,
    BUILTIN_WORKSPACE_VERIFIER_ID,
    BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID,
    get_builtin_agent_by_id,
)

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

AGENT_DEFINITION_MODULE_V2 = "builtin://memstack/agent/definition"
AGENT_DEFINITION_CONTRIBUTION_MODULE_V2 = "builtin://memstack/agent/definition-contribution"
AGENT_DEFINITION_CATALOG_SERVICE_V2 = "service:agent-definition-catalog"
AGENT_DEFINITION_RESOLVER_SERVICE_V2 = "service:agent-definition-resolver"
BUILTIN_AGENT_DEFINITION_IDS_V2 = (
    BUILTIN_ALL_ACCESS_ID,
    BUILTIN_SISYPHUS_ID,
    BUILTIN_WORKSPACE_PLANNER_ID,
    BUILTIN_WORKSPACE_VERIFIER_ID,
    BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    BUILTIN_WORKSPACE_SUPERVISOR_ID,
    BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID,
)

type AgentDefinitionFactoryV2 = Callable[[str, str], object]
type AgentDefinitionProviderV2 = Callable[..., object | Awaitable[object | None] | None]
type AgentDefinitionDisposerV2 = Callable[[], None | Awaitable[None]]


@runtime_checkable
class AgentDefinitionCatalogProtocolV2(Protocol):
    """Mutable contribution catalog owned by one staged generation."""

    def register(
        self,
        agent_id: str,
        factory: AgentDefinitionFactoryV2,
    ) -> AgentDefinitionDisposerV2: ...

    def register_provider(
        self,
        source_id: str,
        provider: AgentDefinitionProviderV2,
    ) -> AgentDefinitionDisposerV2: ...

    def resolve(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> object | None: ...

    async def resolve_provider(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> object | None: ...


class AgentDefinitionCatalogV2:
    """Exact-ID catalog populated only by active Profile contributions."""

    def __init__(self) -> None:
        self._factories: dict[str, AgentDefinitionFactoryV2] = {}
        self._provider: tuple[str, AgentDefinitionProviderV2] | None = None

    def register(
        self,
        agent_id: str,
        factory: AgentDefinitionFactoryV2,
    ) -> AgentDefinitionDisposerV2:
        normalized_agent_id = agent_id.strip()
        if not normalized_agent_id:
            raise RuntimeV2Error(
                "invalid_agent_definition_contribution",
                "agent definition contribution requires a non-empty agent_id",
            )
        if normalized_agent_id in self._factories:
            raise RuntimeV2Error(
                "agent_definition_conflict",
                f"agent definition {normalized_agent_id} already has a contribution",
            )
        self._factories[normalized_agent_id] = factory

        async def dispose() -> None:
            if self._factories.get(normalized_agent_id) is factory:
                _ = self._factories.pop(normalized_agent_id, None)

        return dispose

    def register_provider(
        self,
        source_id: str,
        provider: AgentDefinitionProviderV2,
    ) -> AgentDefinitionDisposerV2:
        normalized_source_id = source_id.strip()
        if not normalized_source_id or not callable(provider):
            raise RuntimeV2Error(
                "invalid_agent_definition_provider",
                "agent definition provider requires a non-empty source_id and callable provider",
            )
        if self._provider is not None:
            raise RuntimeV2Error(
                "agent_definition_provider_conflict",
                f"agent definition provider {self._provider[0]} is already registered",
            )
        binding = (normalized_source_id, provider)
        self._provider = binding

        async def dispose() -> None:
            if self._provider == binding:
                self._provider = None

        return dispose

    def resolve(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> object | None:
        factory = self._factories.get(agent_id)
        if factory is None:
            return None
        result = factory(tenant_id, project_id)
        if getattr(result, "id", None) != agent_id:
            raise RuntimeV2Error(
                "invalid_agent_definition_contribution",
                f"agent definition contribution {agent_id} returned a different id",
            )
        return result

    async def resolve_provider(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> object | None:
        if self._provider is None:
            return None
        source_id, provider = self._provider
        result = provider(
            agent_id=agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if inspect.isawaitable(result):
            result = await result
        if result is not None and getattr(result, "id", None) != agent_id:
            raise RuntimeV2Error(
                "invalid_agent_definition_provider",
                f"agent definition provider {source_id} returned a different id",
            )
        return result


@runtime_checkable
class AgentDefinitionResolverProtocolV2(Protocol):
    """Structural contract consumed by generation-scoped definition callers."""

    async def resolve(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> object | None: ...


@dataclass(frozen=True, kw_only=True)
class AgentDefinitionResolverV2:
    """Resolve an explicit agent ID only through active Profile contributions."""

    strategy: str
    catalog: AgentDefinitionCatalogProtocolV2

    async def resolve(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> object | None:
        if not agent_id.strip():
            raise ValueError("agent_id must be non-empty")
        if not tenant_id.strip():
            raise ValueError("tenant_id must be non-empty")
        contributed = self.catalog.resolve(
            agent_id=agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if contributed is not None or agent_id in BUILTIN_AGENT_DEFINITION_IDS_V2:
            return contributed
        return await self.catalog.resolve_provider(
            agent_id=agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )


def _apply_agent_definition_resolver_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "explicit-id":
        raise ValueError("agent-definition provider requires strategy explicit-id")
    catalog = AgentDefinitionCatalogV2()
    _ = context.provide(
        AGENT_DEFINITION_CATALOG_SERVICE_V2,
        catalog,
        label="agent-definition-catalog",
    )
    _ = context.provide(
        AGENT_DEFINITION_RESOLVER_SERVICE_V2,
        AgentDefinitionResolverV2(strategy=strategy, catalog=catalog),
        label="agent-definition-resolver",
    )


def _apply_builtin_agent_definition_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> AgentDefinitionDisposerV2:
    strategy = config.get("strategy")
    if strategy != "builtin-agent":
        raise ValueError("builtin agent contribution requires strategy builtin-agent")
    agent_id = config.get("agent_id")
    if not isinstance(agent_id, str) or agent_id not in BUILTIN_AGENT_DEFINITION_IDS_V2:
        raise ValueError("builtin agent contribution requires a declared agent_id")
    catalog = context.require("catalog")
    if not isinstance(catalog, AgentDefinitionCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "agent-definition catalog service has an invalid implementation",
        )

    def factory(tenant_id: str, project_id: str) -> object:
        definition = get_builtin_agent_by_id(
            agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if definition is None:
            raise RuntimeV2Error(
                "invalid_agent_definition_contribution",
                f"builtin agent definition {agent_id} is unavailable",
            )
        return definition

    return catalog.register(agent_id, factory)


def builtin_agent_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_DEFINITION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_DEFINITION_MODULE_V2),
        apply=_apply_agent_definition_resolver_v2,
    )


def builtin_agent_definition_contribution_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_DEFINITION_CONTRIBUTION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_DEFINITION_CONTRIBUTION_MODULE_V2),
        apply=_apply_builtin_agent_definition_contribution_v2,
    )


__all__ = [
    "AGENT_DEFINITION_CATALOG_SERVICE_V2",
    "AGENT_DEFINITION_CONTRIBUTION_MODULE_V2",
    "AGENT_DEFINITION_MODULE_V2",
    "AGENT_DEFINITION_RESOLVER_SERVICE_V2",
    "BUILTIN_AGENT_DEFINITION_IDS_V2",
    "AgentDefinitionCatalogProtocolV2",
    "AgentDefinitionCatalogV2",
    "AgentDefinitionResolverProtocolV2",
    "AgentDefinitionResolverV2",
    "builtin_agent_definition_contribution_v2",
    "builtin_agent_definition_v2",
]
