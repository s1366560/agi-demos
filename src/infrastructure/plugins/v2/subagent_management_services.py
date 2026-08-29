"""Generation-owned persistence and application seams for SubAgent management."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.domain.ports.repositories.subagent_repository import SubAgentRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Project, UserProject
from src.infrastructure.adapters.secondary.persistence.sql_subagent_repository import (
    SqlSubAgentRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SUBAGENT_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/subagent-repository-provider"
)
SUBAGENT_REPOSITORY_PROVIDER_SERVICE_V2 = "service:persistence.subagent-repository-provider"
SUBAGENT_MANAGEMENT_MODULE_V2 = "builtin://memstack/application/subagent-management"
SUBAGENT_MANAGEMENT_SERVICE_V2 = "service:application.subagent-management"
SUBAGENT_MANAGEMENT_REPOSITORIES_INJECT_V2 = "repositories"

_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"


class SubAgentManagementErrorV2(RuntimeError):
    """Base failure for the SubAgent management application seam."""


class SubAgentNotFoundV2(SubAgentManagementErrorV2):
    """The requested SubAgent is absent from the exact tenant authority."""


class SubAgentAlreadyExistsV2(SubAgentManagementErrorV2):
    """A SubAgent name already exists in the exact tenant authority."""


class SubAgentAccessDeniedV2(SubAgentManagementErrorV2):
    """The current identity cannot access the requested project scope."""


@dataclass(frozen=True, kw_only=True)
class SubAgentProjectGrantV2:
    """Exact project membership used by one SubAgent operation."""

    project_id: str
    tenant_id: str
    user_id: str


@runtime_checkable
class SubAgentProjectAccessProtocolV2(Protocol):
    async def require_access(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
    ) -> SubAgentProjectGrantV2: ...

    async def accessible_project_ids(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> set[str]: ...


@dataclass(frozen=True, kw_only=True)
class SqlSubAgentProjectAccessV2:
    """Authorize project membership through the operation-owned SQL session."""

    db: AsyncSession

    async def require_access(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
    ) -> SubAgentProjectGrantV2:
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
            raise SubAgentAccessDeniedV2(project_id)
        return SubAgentProjectGrantV2(
            project_id=project_id,
            tenant_id=authorized_tenant_id,
            user_id=user_id,
        )

    async def accessible_project_ids(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> set[str]:
        _require_identifier(tenant_id, field_name="tenant_id")
        _require_identifier(user_id, field_name="user_id")
        result = await self.db.execute(
            refresh_select_statement(
                select(Project.id)
                .select_from(UserProject)
                .join(Project, UserProject.project_id == Project.id)
                .where(
                    UserProject.user_id == user_id,
                    Project.tenant_id == tenant_id,
                )
            )
        )
        return {str(project_id) for project_id in result.scalars().all()}


@dataclass(frozen=True, kw_only=True)
class SubAgentManagementRepositoriesV2:
    """Operation-owned persistence ports used by SubAgent management."""

    db: AsyncSession
    subagents: SubAgentRepositoryPort
    project_access: SubAgentProjectAccessProtocolV2


@runtime_checkable
class SubAgentRepositoryFactoryProtocolV2(Protocol):
    def build(self, operation: OperationContextV2) -> SubAgentManagementRepositoriesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlSubAgentRepositoryFactoryV2:
    """Create SQL adapters without exposing implementations to Consumers."""

    strategy: str

    def build(self, operation: OperationContextV2) -> SubAgentManagementRepositoriesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "SubAgent management requires an AsyncSession operation service",
            )
        return SubAgentManagementRepositoriesV2(
            db=db,
            subagents=SqlSubAgentRepository(db),
            project_access=SqlSubAgentProjectAccessV2(db=db),
        )


@dataclass(frozen=True, kw_only=True)
class SubAgentAccessV2:
    """An authorized SubAgent plus the immutable operation identity."""

    subagent: SubAgent
    tenant_id: str
    user_id: str


@runtime_checkable
class SubAgentManagementServiceProtocolV2(Protocol):
    tenant_id: str
    user_id: str

    async def create(self, subagent: SubAgent) -> SubAgent: ...

    async def list_accessible(self, *, enabled_only: bool) -> list[SubAgent]: ...

    async def require_access(self, subagent_id: str) -> SubAgentAccessV2: ...

    async def update(self, access: SubAgentAccessV2, subagent: SubAgent) -> SubAgent: ...

    async def delete(self, access: SubAgentAccessV2) -> None: ...

    async def set_enabled(self, access: SubAgentAccessV2, *, enabled: bool) -> SubAgent: ...


@dataclass(frozen=True, kw_only=True)
class SubAgentManagementServiceV2:
    """Operation-owned authorization and persistence surface for SubAgents."""

    repositories: SubAgentManagementRepositoriesV2
    tenant_id: str
    user_id: str

    async def create(self, subagent: SubAgent) -> SubAgent:
        self._ensure_tenant(subagent)
        if subagent.project_id is not None:
            _ = await self.repositories.project_access.require_access(
                project_id=subagent.project_id,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
            )
        existing = await self.repositories.subagents.get_by_name(self.tenant_id, subagent.name)
        if existing is not None:
            raise SubAgentAlreadyExistsV2(subagent.name)
        created = await self.repositories.subagents.create(subagent)
        self._ensure_tenant(created)
        await self.repositories.db.commit()
        return created

    async def list_accessible(self, *, enabled_only: bool) -> list[SubAgent]:
        total = await self.repositories.subagents.count_by_tenant(
            self.tenant_id,
            enabled_only=enabled_only,
        )
        if total <= 0:
            return []
        subagents = await self.repositories.subagents.list_by_tenant(
            self.tenant_id,
            enabled_only=enabled_only,
            limit=total,
            offset=0,
        )
        for subagent in subagents:
            self._ensure_tenant(subagent)
        if not any(subagent.project_id for subagent in subagents):
            return subagents
        project_ids = await self.repositories.project_access.accessible_project_ids(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
        )
        return [
            subagent
            for subagent in subagents
            if subagent.project_id is None or subagent.project_id in project_ids
        ]

    async def require_access(self, subagent_id: str) -> SubAgentAccessV2:
        _require_identifier(subagent_id, field_name="subagent_id")
        subagent = await self.repositories.subagents.get_by_id(subagent_id)
        if subagent is None or subagent.tenant_id != self.tenant_id:
            raise SubAgentNotFoundV2(subagent_id)
        if subagent.project_id is not None:
            _ = await self.repositories.project_access.require_access(
                project_id=subagent.project_id,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
            )
        return SubAgentAccessV2(
            subagent=subagent,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
        )

    async def update(self, access: SubAgentAccessV2, subagent: SubAgent) -> SubAgent:
        self._ensure_access_matches(access, subagent)
        if subagent.name != access.subagent.name:
            existing = await self.repositories.subagents.get_by_name(
                self.tenant_id,
                subagent.name,
            )
            if existing is not None and existing.id != subagent.id:
                raise SubAgentAlreadyExistsV2(subagent.name)
        updated = await self.repositories.subagents.update(subagent)
        self._ensure_access_matches(access, updated)
        await self.repositories.db.commit()
        return updated

    async def delete(self, access: SubAgentAccessV2) -> None:
        self._ensure_access_matches(access, access.subagent)
        _ = await self.repositories.subagents.delete(access.subagent.id)
        await self.repositories.db.commit()

    async def set_enabled(self, access: SubAgentAccessV2, *, enabled: bool) -> SubAgent:
        self._ensure_access_matches(access, access.subagent)
        updated = await self.repositories.subagents.set_enabled(access.subagent.id, enabled)
        self._ensure_access_matches(access, updated)
        await self.repositories.db.commit()
        return updated

    def _ensure_tenant(self, subagent: SubAgent) -> None:
        if subagent.tenant_id != self.tenant_id:
            raise SubAgentAccessDeniedV2(subagent.id)

    def _ensure_access_matches(self, access: SubAgentAccessV2, subagent: SubAgent) -> None:
        if (
            access.tenant_id != self.tenant_id
            or access.user_id != self.user_id
            or subagent.id != access.subagent.id
            or subagent.tenant_id != access.subagent.tenant_id
            or subagent.project_id != access.subagent.project_id
        ):
            raise SubAgentAccessDeniedV2(subagent.id)


@runtime_checkable
class SubAgentManagementResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> SubAgentManagementServiceProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SubAgentManagementResolverV2:
    repositories: SubAgentRepositoryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> SubAgentManagementServiceV2:
        scope = operation.context.scope
        if scope.kind is not ScopeKindV2.TENANT or scope.tenant_id is None:
            raise RuntimeV2Error(
                "invalid_subagent_operation_scope",
                "SubAgent management requires an exact tenant operation scope",
            )
        identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
        if not isinstance(identity, Mapping):
            raise RuntimeV2Error(
                "invalid_subagent_operation_identity",
                "SubAgent management requires a structured operation identity",
            )
        identity_mapping = cast("Mapping[str, object]", identity)
        tenant_id = identity_mapping.get("tenant_id")
        user_id = identity_mapping.get("user_id")
        if (
            not isinstance(tenant_id, str)
            or tenant_id != scope.tenant_id
            or not isinstance(user_id, str)
            or not user_id.strip()
        ):
            raise RuntimeV2Error(
                "invalid_subagent_operation_identity",
                "SubAgent management identity does not match the operation scope",
            )
        return SubAgentManagementServiceV2(
            repositories=self.repositories.build(operation),
            tenant_id=scope.tenant_id,
            user_id=user_id,
        )


def _apply_subagent_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("SubAgent repository Provider requires strategy request-async-session")
    _ = context.provide(
        SUBAGENT_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlSubAgentRepositoryFactoryV2(strategy=strategy),
        label="subagent-repository-provider",
    )


def _apply_subagent_management_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("SubAgent management requires strategy operation-scoped-provider")
    repositories = context.require(SUBAGENT_MANAGEMENT_REPOSITORIES_INJECT_V2)
    if not isinstance(repositories, SubAgentRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_subagent_repository_provider",
            "SubAgent management repository Provider has an invalid implementation",
        )
    _ = context.provide(
        SUBAGENT_MANAGEMENT_SERVICE_V2,
        SubAgentManagementResolverV2(repositories=repositories),
        label="subagent-management",
    )


def subagent_management_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the SubAgent repository Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=SUBAGENT_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SUBAGENT_REPOSITORY_PROVIDER_MODULE_V2),
            apply=_apply_subagent_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=SUBAGENT_MANAGEMENT_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SUBAGENT_MANAGEMENT_MODULE_V2),
            apply=_apply_subagent_management_v2,
        ),
    )


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


__all__ = [
    "SUBAGENT_MANAGEMENT_MODULE_V2",
    "SUBAGENT_MANAGEMENT_REPOSITORIES_INJECT_V2",
    "SUBAGENT_MANAGEMENT_SERVICE_V2",
    "SUBAGENT_REPOSITORY_PROVIDER_MODULE_V2",
    "SUBAGENT_REPOSITORY_PROVIDER_SERVICE_V2",
    "SqlSubAgentProjectAccessV2",
    "SqlSubAgentRepositoryFactoryV2",
    "SubAgentAccessDeniedV2",
    "SubAgentAccessV2",
    "SubAgentAlreadyExistsV2",
    "SubAgentManagementErrorV2",
    "SubAgentManagementRepositoriesV2",
    "SubAgentManagementResolverProtocolV2",
    "SubAgentManagementResolverV2",
    "SubAgentManagementServiceProtocolV2",
    "SubAgentManagementServiceV2",
    "SubAgentNotFoundV2",
    "SubAgentProjectAccessProtocolV2",
    "SubAgentProjectGrantV2",
    "SubAgentRepositoryFactoryProtocolV2",
    "subagent_management_definitions_v2",
]
