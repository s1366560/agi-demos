"""Generation-owned Provider/Consumer seams for cluster operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.cluster_service import ClusterService
from src.infrastructure.adapters.secondary.persistence.models import (
    ACPRunnerInstanceModel,
    ACPRunnerPoolModel,
    ACPRunnerTokenModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_acp_runner_repository import (
    ACPRunnerRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cluster_repository import (
    SqlClusterRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CLUSTER_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/cluster-provider"
CLUSTER_PROVIDER_SERVICE_V2 = "service:persistence.cluster-provider"
CLUSTER_APPLICATION_MODULE_V2 = "builtin://memstack/application/cluster-services"
CLUSTER_APPLICATION_SERVICE_V2 = "service:application.cluster-services"
CLUSTER_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class ClusterRunnerPoolServiceV2:
    """Application seam for tenant-scoped ACP runner-pool persistence."""

    _repository: ACPRunnerRepository

    async def list_for_cluster(
        self,
        *,
        tenant_id: str,
        cluster_id: str,
    ) -> tuple[list[ACPRunnerPoolModel], list[ACPRunnerInstanceModel]]:
        pools = await self._repository.list_pools_by_cluster(
            tenant_id=tenant_id,
            cluster_id=cluster_id,
        )
        instances = await self._repository.list_instances_by_tenant(tenant_id)
        return pools, instances

    async def get_by_tenant_key(
        self,
        *,
        tenant_id: str,
        pool_key: str,
    ) -> ACPRunnerPoolModel | None:
        return await self._repository.get_pool_by_tenant_key(
            tenant_id=tenant_id,
            pool_key=pool_key,
        )

    async def get_by_cluster_key(
        self,
        *,
        tenant_id: str,
        cluster_id: str,
        pool_key: str,
    ) -> ACPRunnerPoolModel | None:
        return await self._repository.get_pool_by_cluster_key(
            tenant_id=tenant_id,
            cluster_id=cluster_id,
            pool_key=pool_key,
        )

    async def create(
        self,
        *,
        tenant_id: str,
        cluster_id: str,
        pool_key: str,
        name: str,
        mode: str,
        enabled: bool,
        labels: dict[str, Any],
        capacity_policy: dict[str, Any],
        scheduling_policy: dict[str, Any],
        created_by: str,
    ) -> ACPRunnerPoolModel:
        return await self._repository.create_pool(
            tenant_id=tenant_id,
            cluster_id=cluster_id,
            pool_key=pool_key,
            name=name,
            mode=mode,
            enabled=enabled,
            labels=labels,
            capacity_policy=capacity_policy,
            scheduling_policy=scheduling_policy,
            created_by=created_by,
        )

    async def update(
        self,
        pool: ACPRunnerPoolModel,
        *,
        name: str,
        mode: str,
        enabled: bool,
        labels: dict[str, Any],
        capacity_policy: dict[str, Any],
        scheduling_policy: dict[str, Any],
    ) -> ACPRunnerPoolModel:
        return await self._repository.update_pool(
            pool,
            name=name,
            mode=mode,
            enabled=enabled,
            labels=labels,
            capacity_policy=capacity_policy,
            scheduling_policy=scheduling_policy,
        )

    async def list_instances(self, pool_id: str) -> list[ACPRunnerInstanceModel]:
        return await self._repository.list_instances_by_pool(pool_id)

    async def create_registration_token(
        self,
        *,
        pool: ACPRunnerPoolModel,
        created_by: str,
        name: str | None,
        expires_in_hours: int,
    ) -> tuple[ACPRunnerTokenModel, str]:
        return await self._repository.create_registration_token(
            pool=pool,
            created_by=created_by,
            name=name,
            expires_in_hours=expires_in_hours,
        )


@dataclass(frozen=True, kw_only=True)
class ClusterApplicationServicesV2:
    """Request-owned cluster service set."""

    clusters: ClusterService
    runner_pools: ClusterRunnerPoolServiceV2


@runtime_checkable
class ClusterServiceFactoryProtocolV2(Protocol):
    """Build request services without exposing SQL implementation classes."""

    def build(self, operation: OperationContextV2) -> ClusterApplicationServicesV2: ...


@runtime_checkable
class ClusterApplicationResolverProtocolV2(Protocol):
    """Resolve request services through a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> ClusterApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlClusterServiceFactoryV2:
    """Bind cluster repositories to the operation's exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> ClusterApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "cluster services require an AsyncSession operation service",
            )
        return ClusterApplicationServicesV2(
            clusters=ClusterService(cluster_repo=SqlClusterRepository(db)),
            runner_pools=ClusterRunnerPoolServiceV2(
                _repository=ACPRunnerRepository(db),
            ),
        )


@dataclass(frozen=True, kw_only=True)
class ClusterApplicationResolverV2:
    """Consumer seam for an explicitly selected cluster Provider."""

    provider: ClusterServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> ClusterApplicationServicesV2:
        return self.provider.build(operation)


def _apply_cluster_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "request-async-session":
        raise ValueError("cluster provider requires strategy request-async-session")
    _ = context.provide(
        CLUSTER_PROVIDER_SERVICE_V2,
        SqlClusterServiceFactoryV2(),
        label="cluster-provider",
    )


def _apply_cluster_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("cluster application resolver requires strategy operation-scoped-provider")
    provider = context.require(CLUSTER_PROVIDER_INJECT_V2)
    if not isinstance(provider, ClusterServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_cluster_provider",
            "cluster provider inject does not implement the factory contract",
        )
    _ = context.provide(
        CLUSTER_APPLICATION_SERVICE_V2,
        ClusterApplicationResolverV2(provider=provider),
        label="cluster-application",
    )


def cluster_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for clusters."""
    return (
        PluginDefinitionV2(
            module_ref=CLUSTER_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CLUSTER_PROVIDER_MODULE_V2),
            apply=_apply_cluster_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=CLUSTER_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CLUSTER_APPLICATION_MODULE_V2),
            apply=_apply_cluster_application_v2,
        ),
    )


__all__ = [
    "CLUSTER_APPLICATION_MODULE_V2",
    "CLUSTER_APPLICATION_SERVICE_V2",
    "CLUSTER_PROVIDER_INJECT_V2",
    "CLUSTER_PROVIDER_MODULE_V2",
    "CLUSTER_PROVIDER_SERVICE_V2",
    "ClusterApplicationResolverProtocolV2",
    "ClusterApplicationResolverV2",
    "ClusterApplicationServicesV2",
    "ClusterRunnerPoolServiceV2",
    "ClusterServiceFactoryProtocolV2",
    "SqlClusterServiceFactoryV2",
    "cluster_service_definitions_v2",
]
