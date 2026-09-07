"""Generation-owned persistence and application seams for Agent Definitions."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.agent_definition import Agent
from src.domain.ports.agent.agent_registry import AgentRegistryPort
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Project, UserProject
from src.infrastructure.adapters.secondary.persistence.sql_acp_external_agent_config_repository import (
    ACPExternalAgentConfigRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
    SqlAgentRegistryRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_DEFINITION_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/agent-definition-repository-provider"
)
AGENT_DEFINITION_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.agent-definition-repository-provider"
)
AGENT_DEFINITION_MANAGEMENT_MODULE_V2 = "builtin://memstack/application/agent-definition-management"
AGENT_DEFINITION_MANAGEMENT_SERVICE_V2 = "service:application.agent-definition-management"
AGENT_DEFINITION_MANAGEMENT_REPOSITORIES_INJECT_V2 = "repositories"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class AgentDefinitionManagementRepositoriesV2:
    """Operation-owned persistence adapters used by definition management."""

    db: AsyncSession
    registry: AgentRegistryPort
    external_agents: ACPExternalAgentConfigRepository


@runtime_checkable
class AgentDefinitionRepositoryFactoryProtocolV2(Protocol):
    """Build definition repositories from an operation DB session."""

    def build(
        self,
        operation: OperationContextV2,
    ) -> AgentDefinitionManagementRepositoriesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentDefinitionRepositoryFactoryV2:
    """Create SQL adapters without exposing their implementations to consumers."""

    strategy: str

    def build(
        self,
        operation: OperationContextV2,
    ) -> AgentDefinitionManagementRepositoriesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Agent Definition management requires an AsyncSession operation service",
            )
        return AgentDefinitionManagementRepositoriesV2(
            db=db,
            registry=SqlAgentRegistryRepository(db),
            external_agents=ACPExternalAgentConfigRepository(db),
        )


@runtime_checkable
class AgentDefinitionManagementServiceProtocolV2(Protocol):
    """Application operations available to Agent Definition HTTP authorities."""

    async def create_agent(self, agent: Agent) -> Agent: ...

    async def has_project_access(
        self,
        *,
        user_id: str,
        tenant_id: str,
        project_id: str,
    ) -> bool: ...

    async def accessible_project_ids(
        self,
        *,
        user_id: str,
        tenant_id: str,
    ) -> set[str]: ...

    async def external_agent_enabled(
        self,
        *,
        tenant_id: str,
        agent_key: str,
    ) -> bool | None: ...

    async def get_by_id(self, definition_id: str, *, tenant_id: str) -> Agent | None: ...

    async def list_by_project(
        self,
        *,
        project_id: str,
        tenant_id: str,
        enabled_only: bool,
        limit: int | None,
        offset: int,
        enabled: bool | None,
        search: str | None,
        sort: str | None,
    ) -> list[Agent]: ...

    async def count_by_project(
        self,
        *,
        project_id: str,
        tenant_id: str,
        enabled_only: bool,
        enabled: bool | None,
        search: str | None,
    ) -> int: ...

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
        enabled_only: bool,
        limit: int,
        offset: int,
        project_ids: set[str],
        enabled: bool | None,
        search: str | None,
        sort: str | None,
    ) -> list[Agent]: ...

    async def count_by_tenant(
        self,
        *,
        tenant_id: str,
        enabled_only: bool,
        project_ids: set[str],
        enabled: bool | None,
        search: str | None,
    ) -> int: ...

    async def update_agent(self, agent: Agent) -> Agent: ...

    async def delete_agent(self, definition_id: str) -> bool: ...

    async def set_enabled(self, definition_id: str, enabled: bool) -> Agent: ...


@dataclass(frozen=True, kw_only=True)
class AgentDefinitionManagementServiceV2:
    """Operation-owned Agent Definition CRUD/list service."""

    db: AsyncSession
    registry: AgentRegistryPort
    external_agents: ACPExternalAgentConfigRepository

    async def create_agent(self, agent: Agent) -> Agent:
        agent.validate()
        existing = await self.registry.get_by_name(agent.tenant_id, agent.name)
        if existing is not None:
            raise ValueError(f"Agent with name '{agent.name}' already exists (id={existing.id})")
        created = await self.registry.create(agent)
        await self.db.commit()
        logger.info(
            "Agent definition created through V2: id=%s name=%s tenant=%s",
            created.id,
            created.name,
            created.tenant_id,
        )
        return created

    async def has_project_access(
        self,
        *,
        user_id: str,
        tenant_id: str,
        project_id: str,
    ) -> bool:
        result = await self.db.execute(
            refresh_select_statement(
                select(UserProject.id)
                .join(Project, UserProject.project_id == Project.id)
                .where(
                    and_(
                        UserProject.user_id == user_id,
                        UserProject.project_id == project_id,
                        Project.tenant_id == tenant_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def accessible_project_ids(
        self,
        *,
        user_id: str,
        tenant_id: str,
    ) -> set[str]:
        result = await self.db.execute(
            refresh_select_statement(
                select(UserProject.project_id)
                .join(Project, UserProject.project_id == Project.id)
                .where(
                    and_(
                        UserProject.user_id == user_id,
                        Project.tenant_id == tenant_id,
                    )
                )
            )
        )
        return {str(project_id) for project_id in result.scalars().all()}

    async def external_agent_enabled(
        self,
        *,
        tenant_id: str,
        agent_key: str,
    ) -> bool | None:
        row = await self.external_agents.get_by_tenant_and_key(tenant_id, agent_key)
        return None if row is None else bool(row.enabled)

    async def get_by_id(self, definition_id: str, *, tenant_id: str) -> Agent | None:
        return await self.registry.get_by_id(definition_id, tenant_id=tenant_id)

    async def list_by_project(
        self,
        *,
        project_id: str,
        tenant_id: str,
        enabled_only: bool,
        limit: int | None,
        offset: int,
        enabled: bool | None,
        search: str | None,
        sort: str | None,
    ) -> list[Agent]:
        return await self.registry.list_by_project(
            project_id=project_id,
            tenant_id=tenant_id,
            enabled_only=enabled_only,
            limit=limit,
            offset=offset,
            enabled=enabled,
            search=search,
            sort=sort,
        )

    async def count_by_project(
        self,
        *,
        project_id: str,
        tenant_id: str,
        enabled_only: bool,
        enabled: bool | None,
        search: str | None,
    ) -> int:
        return await self.registry.count_by_project(
            project_id=project_id,
            tenant_id=tenant_id,
            enabled_only=enabled_only,
            enabled=enabled,
            search=search,
        )

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
        enabled_only: bool,
        limit: int,
        offset: int,
        project_ids: set[str],
        enabled: bool | None,
        search: str | None,
        sort: str | None,
    ) -> list[Agent]:
        return await self.registry.list_by_tenant(
            tenant_id=tenant_id,
            enabled_only=enabled_only,
            limit=limit,
            offset=offset,
            project_ids=project_ids,
            enabled=enabled,
            search=search,
            sort=sort,
        )

    async def count_by_tenant(
        self,
        *,
        tenant_id: str,
        enabled_only: bool,
        project_ids: set[str],
        enabled: bool | None,
        search: str | None,
    ) -> int:
        return await self.registry.count_by_tenant(
            tenant_id=tenant_id,
            enabled_only=enabled_only,
            project_ids=project_ids,
            enabled=enabled,
            search=search,
        )

    async def update_agent(self, agent: Agent) -> Agent:
        updated = await self.registry.update(agent)
        await self.db.commit()
        return updated

    async def delete_agent(self, definition_id: str) -> bool:
        deleted = await self.registry.delete(definition_id)
        await self.db.commit()
        return deleted

    async def set_enabled(self, definition_id: str, enabled: bool) -> Agent:
        updated = await self.registry.set_enabled(definition_id, enabled)
        await self.db.commit()
        return updated


@runtime_checkable
class AgentDefinitionManagementResolverProtocolV2(Protocol):
    """Resolve one management service from declared Provider aliases."""

    def resolve(
        self,
        operation: OperationContextV2,
    ) -> AgentDefinitionManagementServiceProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentDefinitionManagementResolverV2:
    repositories: AgentDefinitionRepositoryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> AgentDefinitionManagementServiceV2:
        repositories = self.repositories.build(operation)
        return AgentDefinitionManagementServiceV2(
            db=repositories.db,
            registry=repositories.registry,
            external_agents=repositories.external_agents,
        )


def _apply_agent_definition_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "Agent Definition repository provider requires strategy request-async-session"
        )
    _ = context.provide(
        AGENT_DEFINITION_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlAgentDefinitionRepositoryFactoryV2(strategy=strategy),
        label="agent-definition-repository-provider",
    )


def _apply_agent_definition_management_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("Agent Definition management requires strategy operation-scoped-provider")
    repositories = context.require(AGENT_DEFINITION_MANAGEMENT_REPOSITORIES_INJECT_V2)
    if not isinstance(repositories, AgentDefinitionRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_definition_repository_provider",
            "Agent Definition management repository Provider has an invalid implementation",
        )
    _ = context.provide(
        AGENT_DEFINITION_MANAGEMENT_SERVICE_V2,
        AgentDefinitionManagementResolverV2(repositories=repositories),
        label="agent-definition-management",
    )


def agent_definition_management_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the definition repository Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=AGENT_DEFINITION_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                AGENT_DEFINITION_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_agent_definition_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_DEFINITION_MANAGEMENT_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_DEFINITION_MANAGEMENT_MODULE_V2),
            apply=_apply_agent_definition_management_v2,
        ),
    )


__all__ = [
    "AGENT_DEFINITION_MANAGEMENT_MODULE_V2",
    "AGENT_DEFINITION_MANAGEMENT_REPOSITORIES_INJECT_V2",
    "AGENT_DEFINITION_MANAGEMENT_SERVICE_V2",
    "AGENT_DEFINITION_REPOSITORY_PROVIDER_MODULE_V2",
    "AGENT_DEFINITION_REPOSITORY_PROVIDER_SERVICE_V2",
    "AgentDefinitionManagementRepositoriesV2",
    "AgentDefinitionManagementResolverProtocolV2",
    "AgentDefinitionManagementResolverV2",
    "AgentDefinitionManagementServiceProtocolV2",
    "AgentDefinitionManagementServiceV2",
    "AgentDefinitionRepositoryFactoryProtocolV2",
    "SqlAgentDefinitionRepositoryFactoryV2",
    "agent_definition_management_definitions_v2",
]
