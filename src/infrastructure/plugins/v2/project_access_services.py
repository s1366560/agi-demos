"""Generation-owned project membership authorization seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Project, UserProject

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

PROJECT_ACCESS_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/project-access-provider"
PROJECT_ACCESS_PROVIDER_SERVICE_V2 = "service:persistence.project-access-provider"
PROJECT_ACCESS_APPLICATION_MODULE_V2 = "builtin://memstack/application/project-access"
PROJECT_ACCESS_APPLICATION_SERVICE_V2 = "service:application.project-access"
PROJECT_ACCESS_PROVIDER_INJECT_V2 = "provider"

_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


class ProjectAccessErrorV2(RuntimeError):
    """Base error for project membership authorization failures."""


class ProjectAccessDeniedV2(ProjectAccessErrorV2):
    """The exact user, tenant, and project membership tuple is absent."""


@dataclass(frozen=True, kw_only=True)
class ProjectAccessGrantV2:
    project_id: str
    tenant_id: str
    user_id: str


@runtime_checkable
class ProjectAccessTransactionProtocolV2(Protocol):
    async def require_access(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ProjectAccessGrantV2: ...


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True, kw_only=True)
class SqlProjectAccessTransactionV2:
    """Authorize one exact membership through an operation-owned SQL session."""

    db: AsyncSession

    async def require_access(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ProjectAccessGrantV2:
        _require_identifier(project_id, field_name="project_id")
        _require_identifier(tenant_id, field_name="tenant_id")
        _require_identifier(user_id, field_name="user_id")
        result = await self.db.execute(
            refresh_select_statement(
                select(Project.tenant_id)
                .select_from(UserProject)
                .join(Project, UserProject.project_id == Project.id)
                .where(
                    UserProject.user_id == user_id,
                    UserProject.project_id == project_id,
                    Project.tenant_id == tenant_id,
                )
            )
        )
        authorized_tenant_id = cast("str | None", result.scalar_one_or_none())
        if authorized_tenant_id is None:
            raise ProjectAccessDeniedV2(project_id)
        return ProjectAccessGrantV2(
            project_id=project_id,
            tenant_id=authorized_tenant_id,
            user_id=user_id,
        )


@runtime_checkable
class ProjectAccessProviderProtocolV2(Protocol):
    def build(self, operation: OperationContextV2) -> ProjectAccessTransactionProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlProjectAccessProviderV2:
    strategy: str

    def build(self, operation: OperationContextV2) -> ProjectAccessTransactionProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "project access requires an AsyncSession operation service",
            )
        return SqlProjectAccessTransactionV2(db=db)


@dataclass(frozen=True, kw_only=True)
class ProjectAccessServiceV2:
    transaction: ProjectAccessTransactionProtocolV2

    async def require_access(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ProjectAccessGrantV2:
        return await self.transaction.require_access(
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )


@runtime_checkable
class ProjectAccessResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> ProjectAccessServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class ProjectAccessResolverV2:
    provider: ProjectAccessProviderProtocolV2

    def resolve(self, operation: OperationContextV2) -> ProjectAccessServiceV2:
        return ProjectAccessServiceV2(transaction=self.provider.build(operation))


def _apply_project_access_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("project access Provider requires strategy request-async-session")
    _ = context.provide(
        PROJECT_ACCESS_PROVIDER_SERVICE_V2,
        SqlProjectAccessProviderV2(strategy=strategy),
        label="project-access-provider",
    )


def _apply_project_access_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("project access requires strategy operation-scoped-provider")
    provider = context.require(PROJECT_ACCESS_PROVIDER_INJECT_V2)
    if not isinstance(provider, ProjectAccessProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_project_access_provider",
            "project access Provider has an invalid implementation",
        )
    _ = context.provide(
        PROJECT_ACCESS_APPLICATION_SERVICE_V2,
        ProjectAccessResolverV2(provider=provider),
        label="project-access",
    )


def project_access_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=PROJECT_ACCESS_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(PROJECT_ACCESS_PROVIDER_MODULE_V2),
            apply=_apply_project_access_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=PROJECT_ACCESS_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(PROJECT_ACCESS_APPLICATION_MODULE_V2),
            apply=_apply_project_access_v2,
        ),
    )


__all__ = [
    "PROJECT_ACCESS_APPLICATION_MODULE_V2",
    "PROJECT_ACCESS_APPLICATION_SERVICE_V2",
    "PROJECT_ACCESS_PROVIDER_INJECT_V2",
    "PROJECT_ACCESS_PROVIDER_MODULE_V2",
    "PROJECT_ACCESS_PROVIDER_SERVICE_V2",
    "ProjectAccessDeniedV2",
    "ProjectAccessErrorV2",
    "ProjectAccessGrantV2",
    "ProjectAccessProviderProtocolV2",
    "ProjectAccessResolverProtocolV2",
    "ProjectAccessResolverV2",
    "ProjectAccessServiceV2",
    "ProjectAccessTransactionProtocolV2",
    "SqlProjectAccessProviderV2",
    "SqlProjectAccessTransactionV2",
    "project_access_definitions_v2",
]
