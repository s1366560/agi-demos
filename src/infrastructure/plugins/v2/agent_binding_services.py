# pyright: reportImportCycles=false
"""Generation-owned application seam for tenant AgentBinding management."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.model.agent.agent_definition import Agent
from src.domain.ports.agent.binding_repository import AgentBindingRepositoryPort

from .agent_definition import AgentDefinitionResolverProtocolV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_BINDING_MODULE_V2 = "builtin://memstack/application/agent-bindings"
AGENT_BINDING_SERVICE_V2 = "service:application.agent-bindings"
AGENT_BINDING_DEFINITIONS_INJECT_V2 = "agent_definitions"

type AgentBindingRepositoryFactoryV2 = Callable[[object], AgentBindingRepositoryPort]


class AgentBindingErrorV2(RuntimeError):
    """Base failure for the AgentBinding application seam."""


class AgentBindingNotFoundV2(AgentBindingErrorV2):
    """The requested binding does not exist."""


class AgentBindingScopeMismatchV2(AgentBindingErrorV2):
    """A binding escaped the operation's exact tenant scope."""


class AgentBindingAgentUnavailableV2(AgentBindingErrorV2):
    """The requested Agent Definition cannot own a tenant-level binding."""


@dataclass(frozen=True, kw_only=True)
class AgentBindingMatchV2:
    """One deterministic binding resolution and its persisted decision trace."""

    binding: AgentBinding | None
    agent_name: str | None
    trace: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, kw_only=True)
class AgentBindingServiceV2:
    """Operation-owned CRUD and deterministic matching for AgentBinding rows."""

    operation: OperationContextV2
    binding_repository: AgentBindingRepositoryPort
    agent_definitions: AgentDefinitionResolverProtocolV2

    @property
    def tenant_id(self) -> str:
        tenant_id = self.operation.context.scope.tenant_id
        if tenant_id is None:
            raise RuntimeV2Error(
                "invalid_agent_binding_scope",
                "AgentBinding service requires a tenant-scoped operation",
            )
        return tenant_id

    async def create(self, binding: AgentBinding) -> AgentBinding:
        self._require_binding_scope(binding)
        agent = await self.agent_definitions.resolve(
            agent_id=binding.agent_id,
            tenant_id=self.tenant_id,
            project_id=None,
        )
        if (
            not isinstance(agent, Agent)
            or agent.tenant_id != self.tenant_id
            or agent.project_id is not None
        ):
            raise AgentBindingAgentUnavailableV2(binding.agent_id)
        return await self.binding_repository.create(binding)

    async def list_bindings(
        self,
        *,
        agent_id: str | None,
        enabled_only: bool,
    ) -> list[AgentBinding]:
        if agent_id is not None:
            _require_identifier(agent_id, field_name="agent_id")
            bindings = await self.binding_repository.list_by_agent(
                agent_id=agent_id,
                enabled_only=enabled_only,
            )
        else:
            bindings = await self.binding_repository.list_by_tenant(
                tenant_id=self.tenant_id,
                enabled_only=enabled_only,
            )
        return [binding for binding in bindings if binding.tenant_id == self.tenant_id]

    async def delete(self, binding_id: str) -> bool:
        existing = await self._get_exact(binding_id)
        return await self.binding_repository.delete(existing.id)

    async def set_enabled(self, binding_id: str, *, enabled: bool) -> AgentBinding:
        existing = await self._get_exact(binding_id)
        updated = await self.binding_repository.set_enabled(existing.id, enabled)
        self._require_binding_scope(updated)
        return updated

    async def list_group(self, group_id: str) -> list[AgentBinding]:
        _require_identifier(group_id, field_name="group_id")
        bindings = await self.binding_repository.find_by_group(
            tenant_id=self.tenant_id,
            group_id=group_id,
        )
        return [binding for binding in bindings if binding.tenant_id == self.tenant_id]

    async def resolve_with_trace(
        self,
        *,
        channel_type: str,
        channel_id: str | None,
        account_id: str | None,
        peer_id: str | None,
    ) -> AgentBindingMatchV2:
        _require_identifier(channel_type, field_name="channel_type")
        binding, raw_trace = await self.binding_repository.resolve_binding_with_trace(
            tenant_id=self.tenant_id,
            channel_type=channel_type,
            channel_id=channel_id,
            account_id=account_id,
            peer_id=peer_id,
        )
        agent_name: str | None = None
        if binding is not None:
            self._require_binding_scope(binding)
            agent = await self.agent_definitions.resolve(
                agent_id=binding.agent_id,
                tenant_id=self.tenant_id,
                project_id=None,
            )
            if (
                isinstance(agent, Agent)
                and agent.tenant_id == self.tenant_id
                and agent.project_id is None
            ):
                agent_name = agent.name
        return AgentBindingMatchV2(
            binding=binding,
            agent_name=agent_name,
            trace=tuple(dict(entry) for entry in raw_trace),
        )

    async def _get_exact(self, binding_id: str) -> AgentBinding:
        _require_identifier(binding_id, field_name="binding_id")
        existing = await self.binding_repository.get_by_id(binding_id)
        if existing is None:
            raise AgentBindingNotFoundV2(binding_id)
        self._require_binding_scope(existing)
        return existing

    def _require_binding_scope(self, binding: AgentBinding) -> None:
        if binding.tenant_id != self.tenant_id:
            raise AgentBindingScopeMismatchV2(binding.id)


@runtime_checkable
class AgentBindingResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> AgentBindingServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentBindingResolverV2:
    binding_repository_factory: AgentBindingRepositoryFactoryV2
    agent_definitions: AgentDefinitionResolverProtocolV2

    def resolve(self, operation: OperationContextV2) -> AgentBindingServiceV2:
        from src.domain.model.plugins.generated_v2 import ScopeKindV2

        from .boundary import OPERATION_DB_SESSION_SERVICE_V2

        scope = operation.context.scope
        if (
            scope.kind is not ScopeKindV2.TENANT
            or scope.tenant_id is None
            or scope.project_id is not None
        ):
            raise RuntimeV2Error(
                "invalid_agent_binding_scope",
                "AgentBinding service requires a tenant-scoped operation",
            )
        db_session = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
        return AgentBindingServiceV2(
            operation=operation,
            binding_repository=self.binding_repository_factory(db_session),
            agent_definitions=self.agent_definitions,
        )


def _build_binding_repository_v2(db_session: object) -> AgentBindingRepositoryPort:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.infrastructure.adapters.secondary.persistence.sql_binding_repository import (
        SqlAgentBindingRepository,
    )

    if not isinstance(db_session, AsyncSession):
        raise RuntimeV2Error(
            "invalid_operation_db_session",
            "AgentBinding service requires an AsyncSession operation service",
        )
    return SqlAgentBindingRepository(db_session)


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _apply_agent_binding_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("AgentBinding service requires strategy operation-scoped-provider")
    agent_definitions = context.require(AGENT_BINDING_DEFINITIONS_INJECT_V2)
    if not isinstance(agent_definitions, AgentDefinitionResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_binding_definitions",
            "AgentBinding service requires an Agent Definition resolver",
        )
    _ = context.provide(
        AGENT_BINDING_SERVICE_V2,
        AgentBindingResolverV2(
            binding_repository_factory=_build_binding_repository_v2,
            agent_definitions=agent_definitions,
        ),
        label="agent-bindings",
    )


def agent_binding_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_BINDING_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_BINDING_MODULE_V2),
        apply=_apply_agent_binding_v2,
    )


__all__ = [
    "AGENT_BINDING_DEFINITIONS_INJECT_V2",
    "AGENT_BINDING_MODULE_V2",
    "AGENT_BINDING_SERVICE_V2",
    "AgentBindingAgentUnavailableV2",
    "AgentBindingErrorV2",
    "AgentBindingMatchV2",
    "AgentBindingNotFoundV2",
    "AgentBindingResolverProtocolV2",
    "AgentBindingResolverV2",
    "AgentBindingScopeMismatchV2",
    "AgentBindingServiceV2",
    "agent_binding_definition_v2",
]
