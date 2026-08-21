"""Generation-owned persistence, project, and tenant service seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.project_service import ProjectService
from src.application.services.tenant_service import TenantService
from src.domain.ports.repositories.project_repository import ProjectRepository
from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
    SqlProjectRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_repository import (
    SqlTenantRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlUserRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

PROJECT_TENANT_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/project-tenant-provider"
PROJECT_TENANT_PROVIDER_SERVICE_V2 = "service:persistence.project-tenant-provider"
PROJECT_TENANT_APPLICATION_MODULE_V2 = "builtin://memstack/application/project-tenant-services"
PROJECT_TENANT_APPLICATION_SERVICE_V2 = "service:application.project-tenant-services"
PROJECT_TENANT_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class ProjectTenantServicesV2:
    """One request-session-owned project/tenant service set."""

    project_repository: ProjectRepository
    project_service: ProjectService
    tenant_service: TenantService


@runtime_checkable
class ProjectTenantServiceFactoryProtocolV2(Protocol):
    """Consumer-visible factory contract; callers never name the SQL implementation."""

    def build(self, operation: OperationContextV2) -> ProjectTenantServicesV2: ...


@runtime_checkable
class ProjectTenantApplicationResolverProtocolV2(Protocol):
    """Application-facing resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> ProjectTenantServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlProjectTenantServiceFactoryV2:
    """Build services from the exact AsyncSession supplied by an operation boundary."""

    strategy: str

    def build(self, operation: OperationContextV2) -> ProjectTenantServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "project/tenant services require an AsyncSession operation service",
            )
        project_repository = SqlProjectRepository(db)
        return ProjectTenantServicesV2(
            project_repository=project_repository,
            project_service=ProjectService(
                project_repo=SqlProjectRepository(db),
                user_repo=SqlUserRepository(db),
            ),
            tenant_service=TenantService(
                tenant_repo=SqlTenantRepository(db),
                user_repo=SqlUserRepository(db),
            ),
        )


@dataclass(frozen=True, kw_only=True)
class ProjectTenantApplicationResolverV2:
    """Resolve one request-owned service set without exposing a Provider implementation."""

    provider: ProjectTenantServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> ProjectTenantServicesV2:
        return self.provider.build(operation)


def _apply_project_tenant_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("project/tenant provider requires strategy request-async-session")
    _ = context.provide(
        PROJECT_TENANT_PROVIDER_SERVICE_V2,
        SqlProjectTenantServiceFactoryV2(strategy=strategy),
        label="project-tenant-provider",
    )


def _apply_project_tenant_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "operation-scoped-provider":
        raise ValueError(
            "project/tenant application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(PROJECT_TENANT_PROVIDER_INJECT_V2)
    if not isinstance(provider, ProjectTenantServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_project_tenant_provider",
            "project/tenant provider inject does not implement the factory contract",
        )
    _ = context.provide(
        PROJECT_TENANT_APPLICATION_SERVICE_V2,
        ProjectTenantApplicationResolverV2(provider=provider),
        label="project-tenant-application",
    )


def project_tenant_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=PROJECT_TENANT_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(PROJECT_TENANT_PROVIDER_MODULE_V2),
            apply=_apply_project_tenant_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=PROJECT_TENANT_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(PROJECT_TENANT_APPLICATION_MODULE_V2),
            apply=_apply_project_tenant_application_v2,
        ),
    )


__all__ = [
    "PROJECT_TENANT_APPLICATION_MODULE_V2",
    "PROJECT_TENANT_APPLICATION_SERVICE_V2",
    "PROJECT_TENANT_PROVIDER_INJECT_V2",
    "PROJECT_TENANT_PROVIDER_MODULE_V2",
    "PROJECT_TENANT_PROVIDER_SERVICE_V2",
    "ProjectTenantApplicationResolverProtocolV2",
    "ProjectTenantApplicationResolverV2",
    "ProjectTenantServiceFactoryProtocolV2",
    "ProjectTenantServicesV2",
    "SqlProjectTenantServiceFactoryV2",
    "project_tenant_service_definitions_v2",
]
