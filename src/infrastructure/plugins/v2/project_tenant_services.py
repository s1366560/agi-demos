"""Generation-owned persistence/project/tenant Provider and shadow Consumer seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.project_service import ProjectService
from src.application.services.tenant_service import TenantService
from src.domain.model.plugins.generated_v2 import ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
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
PROJECT_TENANT_SHADOW_MODULE_V2 = "builtin://memstack/persistence/project-tenant-shadow"
PROJECT_TENANT_SHADOW_SERVICE_V2 = "service:persistence.project-tenant-shadow"
PROJECT_TENANT_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class ProjectTenantServicesV2:
    """One request-session-owned project/tenant service set."""

    project_repository: ProjectRepository
    project_service: ProjectService
    tenant_service: TenantService


@dataclass(frozen=True, kw_only=True)
class ProjectTenantShadowEvidenceV2:
    """Objective parity evidence emitted by the non-authoritative shadow Consumer."""

    operation_id: str
    scope: ScopeV2
    descriptor: PluginGenerationDescriptorV2 | None
    matches: bool
    differences: tuple[str, ...]
    error_code: str | None = None

    @classmethod
    def failed(
        cls,
        *,
        operation_id: str,
        scope: ScopeV2,
        descriptor: PluginGenerationDescriptorV2 | None,
        error_code: str,
        difference: str,
    ) -> ProjectTenantShadowEvidenceV2:
        return cls(
            operation_id=operation_id,
            scope=scope,
            descriptor=descriptor,
            matches=False,
            differences=(difference,),
            error_code=error_code,
        )


@runtime_checkable
class ProjectTenantServiceFactoryProtocolV2(Protocol):
    """Consumer-visible factory contract; callers never name the SQL implementation."""

    def build(self, operation: OperationContextV2) -> ProjectTenantServicesV2: ...


@runtime_checkable
class ProjectTenantApplicationResolverProtocolV2(Protocol):
    """Application-facing resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> ProjectTenantServicesV2: ...


@runtime_checkable
class ProjectTenantShadowProtocolV2(Protocol):
    """Boundary-visible Consumer contract with no concrete implementation dependency."""

    def compare(
        self,
        *,
        operation: OperationContextV2,
        legacy: ProjectTenantServicesV2,
        expected_scope: ScopeV2,
    ) -> ProjectTenantShadowEvidenceV2: ...


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


@dataclass(frozen=True, kw_only=True)
class ProjectTenantShadowComparatorV2:
    """Compare V2 and legacy constructions without selecting either implementation."""

    provider: ProjectTenantServiceFactoryProtocolV2

    def compare(
        self,
        *,
        operation: OperationContextV2,
        legacy: ProjectTenantServicesV2,
        expected_scope: ScopeV2,
    ) -> ProjectTenantShadowEvidenceV2:
        candidate = self.provider.build(operation)
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        differences: list[str] = []

        if operation.context.scope != expected_scope:
            differences.append("operation.scope")

        for label, candidate_value, legacy_value in _service_rows(candidate, legacy):
            if type(candidate_value) is not type(legacy_value):
                differences.append(f"{label}.type")

        for label, candidate_repository, legacy_repository in _repository_rows(
            candidate,
            legacy,
        ):
            if type(candidate_repository) is not type(legacy_repository):
                differences.append(f"{label}.type")
            if getattr(candidate_repository, "_session", None) is not db:
                differences.append(f"{label}.candidate_session")
            if getattr(legacy_repository, "_session", None) is not db:
                differences.append(f"{label}.legacy_session")

        return ProjectTenantShadowEvidenceV2(
            operation_id=operation.operation_id,
            scope=operation.context.scope,
            descriptor=operation.descriptor,
            matches=not differences,
            differences=tuple(differences),
        )


def _service_rows(
    candidate: ProjectTenantServicesV2,
    legacy: ProjectTenantServicesV2,
) -> tuple[tuple[str, object, object], ...]:
    return (
        ("project_repository", candidate.project_repository, legacy.project_repository),
        ("project_service", candidate.project_service, legacy.project_service),
        ("tenant_service", candidate.tenant_service, legacy.tenant_service),
    )


def _repository_rows(
    candidate: ProjectTenantServicesV2,
    legacy: ProjectTenantServicesV2,
) -> tuple[tuple[str, object, object], ...]:
    return (
        ("project_repository", candidate.project_repository, legacy.project_repository),
        (
            "project_service.project_repository",
            getattr(candidate.project_service, "_project_repo", None),
            getattr(legacy.project_service, "_project_repo", None),
        ),
        (
            "project_service.user_repository",
            getattr(candidate.project_service, "_user_repo", None),
            getattr(legacy.project_service, "_user_repo", None),
        ),
        (
            "tenant_service.tenant_repository",
            getattr(candidate.tenant_service, "_tenant_repo", None),
            getattr(legacy.tenant_service, "_tenant_repo", None),
        ),
        (
            "tenant_service.user_repository",
            getattr(candidate.tenant_service, "_user_repo", None),
            getattr(legacy.tenant_service, "_user_repo", None),
        ),
    )


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


def _apply_project_tenant_shadow_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "structural-parity":
        raise ValueError("project/tenant shadow requires strategy structural-parity")
    provider = context.require(PROJECT_TENANT_PROVIDER_INJECT_V2)
    if not isinstance(provider, ProjectTenantServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_project_tenant_provider",
            "project/tenant provider inject does not implement the factory contract",
        )
    _ = context.provide(
        PROJECT_TENANT_SHADOW_SERVICE_V2,
        ProjectTenantShadowComparatorV2(provider=provider),
        label="project-tenant-shadow",
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
        PluginDefinitionV2(
            module_ref=PROJECT_TENANT_SHADOW_MODULE_V2,
            contract_digest=generated_contract_digest_v2(PROJECT_TENANT_SHADOW_MODULE_V2),
            apply=_apply_project_tenant_shadow_v2,
        ),
    )


__all__ = [
    "PROJECT_TENANT_APPLICATION_MODULE_V2",
    "PROJECT_TENANT_APPLICATION_SERVICE_V2",
    "PROJECT_TENANT_PROVIDER_INJECT_V2",
    "PROJECT_TENANT_PROVIDER_MODULE_V2",
    "PROJECT_TENANT_PROVIDER_SERVICE_V2",
    "PROJECT_TENANT_SHADOW_MODULE_V2",
    "PROJECT_TENANT_SHADOW_SERVICE_V2",
    "ProjectTenantApplicationResolverProtocolV2",
    "ProjectTenantApplicationResolverV2",
    "ProjectTenantServiceFactoryProtocolV2",
    "ProjectTenantServicesV2",
    "ProjectTenantShadowComparatorV2",
    "ProjectTenantShadowEvidenceV2",
    "ProjectTenantShadowProtocolV2",
    "SqlProjectTenantServiceFactoryV2",
    "project_tenant_service_definitions_v2",
]
