"""Generation-scoped channel agent-routing Provider for the v2 runtime spine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from src.domain.model.agent.agent_definition import Agent
from src.domain.ports.agent.binding_repository import AgentBindingRepositoryPort

from .agent_definition import AgentDefinitionResolverProtocolV2
from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

AGENT_ROUTING_MODULE_V2 = "builtin://memstack/agent/routing"
AGENT_ROUTE_RESOLVER_SERVICE_V2 = "service:agent-route-resolver"

type AgentBindingRepositoryFactoryV2 = Callable[[object], AgentBindingRepositoryPort]
type AgentRouteSourceV2 = Literal["binding", "profile-default"]


@dataclass(frozen=True, kw_only=True)
class AgentRouteResolutionV2:
    """Explicit agent selected for one pinned channel operation."""

    agent: Agent
    agent_id: str
    binding_id: str | None
    source: AgentRouteSourceV2


@runtime_checkable
class AgentRouteResolverProtocolV2(Protocol):
    """Structural contract consumed by channel operation boundaries."""

    async def resolve(
        self,
        *,
        tenant_id: str,
        project_id: str,
        channel_type: str | None = None,
        channel_id: str | None = None,
        account_id: str | None = None,
        peer_id: str | None = None,
    ) -> AgentRouteResolutionV2: ...


def _build_binding_repository_v2(db_session: object) -> AgentBindingRepositoryPort:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.infrastructure.adapters.secondary.persistence.sql_binding_repository import (
        SqlAgentBindingRepository,
    )

    if not isinstance(db_session, AsyncSession):
        raise RuntimeV2Error(
            "invalid_operation_db_session",
            "agent routing requires an AsyncSession operation service",
        )
    return SqlAgentBindingRepository(db_session)


@dataclass(frozen=True, kw_only=True)
class AgentRouteResolverV2:
    """Resolve bindings and Profile default through one generation-owned definition seam."""

    default_agent_id: str
    definition_resolver: AgentDefinitionResolverProtocolV2
    binding_repository_factory: AgentBindingRepositoryFactoryV2

    async def resolve(
        self,
        *,
        tenant_id: str,
        project_id: str,
        channel_type: str | None = None,
        channel_id: str | None = None,
        account_id: str | None = None,
        peer_id: str | None = None,
    ) -> AgentRouteResolutionV2:
        from .boundary import OPERATION_DB_SESSION_SERVICE_V2, current_operation_context_v2

        if not tenant_id.strip() or not project_id.strip():
            raise RuntimeV2Error(
                "invalid_agent_route_scope",
                "agent routing requires non-empty tenant and project scopes",
            )
        operation = current_operation_context_v2()
        scope = operation.context.scope
        if scope.tenant_id != tenant_id or scope.project_id != project_id:
            raise RuntimeV2Error(
                "agent_route_scope_mismatch",
                "agent routing scope does not match the pinned operation",
            )

        db_session = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
        binding_repository = self.binding_repository_factory(db_session)
        binding = await binding_repository.resolve_binding(
            tenant_id=tenant_id,
            channel_type=channel_type,
            channel_id=channel_id,
            account_id=account_id,
            peer_id=peer_id,
        )
        if binding is not None and binding.tenant_id != tenant_id:
            raise RuntimeV2Error(
                "agent_route_scope_mismatch",
                "agent binding tenant does not match the pinned operation",
            )

        selected_agent_id = binding.agent_id if binding is not None else self.default_agent_id
        selected = await self.definition_resolver.resolve(
            agent_id=selected_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if selected is None:
            raise RuntimeV2Error(
                "agent_route_definition_not_found",
                f"agent route definition {selected_agent_id} is unavailable",
            )
        if not isinstance(selected, Agent):
            raise RuntimeV2Error(
                "invalid_service_implementation",
                "agent-definition resolver returned an invalid agent",
            )
        if selected.tenant_id != tenant_id or selected.project_id not in {None, project_id}:
            raise RuntimeV2Error(
                "agent_route_scope_mismatch",
                "resolved agent definition does not match the pinned operation scope",
            )
        if not selected.is_enabled():
            raise RuntimeV2Error(
                "agent_route_definition_disabled",
                f"agent route definition {selected_agent_id} is disabled",
            )

        return AgentRouteResolutionV2(
            agent=selected,
            agent_id=selected_agent_id,
            binding_id=(binding.id if binding is not None else None),
            source=("binding" if binding is not None else "profile-default"),
        )


def _apply_agent_routing_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    default_agent_id = config.get("default_agent_id")
    if not isinstance(default_agent_id, str) or not default_agent_id.strip():
        raise ValueError("agent-routing provider requires a non-empty default_agent_id")
    definition_resolver = context.require("definition_resolver")
    if not isinstance(definition_resolver, AgentDefinitionResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "agent-definition resolver service has an invalid implementation",
        )
    _ = context.provide(
        AGENT_ROUTE_RESOLVER_SERVICE_V2,
        AgentRouteResolverV2(
            default_agent_id=default_agent_id,
            definition_resolver=definition_resolver,
            binding_repository_factory=_build_binding_repository_v2,
        ),
        label="agent-route-resolver",
    )


def builtin_agent_routing_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_ROUTING_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_ROUTING_MODULE_V2),
        apply=_apply_agent_routing_v2,
    )


__all__ = [
    "AGENT_ROUTE_RESOLVER_SERVICE_V2",
    "AGENT_ROUTING_MODULE_V2",
    "AgentRouteResolutionV2",
    "AgentRouteResolverProtocolV2",
    "AgentRouteResolverV2",
    "builtin_agent_routing_definition_v2",
]
