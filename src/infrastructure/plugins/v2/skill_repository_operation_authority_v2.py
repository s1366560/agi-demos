"""Skill repository authority nested inside an already-pinned V2 operation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort

from .boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from .runtime import OperationContextV2, RuntimeV2Error
from .skill_repository_services import (
    SkillRepositoryApplicationResolverProtocolV2,
    SkillRepositoryApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class SkillRepositoryOperationAuthorityV2:
    """Repositories resolved from a disposable child of one pinned operation."""

    operation: OperationContextV2
    repository: SkillRepositoryPort
    version_repository: SkillVersionRepositoryPort


@asynccontextmanager
async def skill_repository_child_operation_authority_v2(
    *,
    parent_operation: OperationContextV2,
    resolver: object,
    db: AsyncSession,
    consumer: str,
) -> AsyncIterator[SkillRepositoryOperationAuthorityV2]:
    """Resolve Skill repositories without leaving the parent's immutable generation."""
    normalized_consumer = consumer.strip()
    if not normalized_consumer:
        raise RuntimeV2Error(
            "skill_repository_consumer_missing",
            "Skill repository child authority requires a non-empty consumer",
        )
    if not isinstance(resolver, SkillRepositoryApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_skill_repository_application_resolver",
            "Skill repository child authority received an invalid resolver",
        )

    scope = parent_operation.context.scope
    if not scope.tenant_id:
        raise RuntimeV2Error(
            "skill_repository_tenant_missing",
            "Skill repository child authority requires a tenant-scoped parent operation",
        )
    raw_identity = parent_operation.require(OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(raw_identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "Skill repository parent operation identity must be an object",
        )
    identity_values = cast("Mapping[object, object]", raw_identity)
    if any(not isinstance(key, str) for key in identity_values):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "Skill repository parent operation identity keys must be strings",
        )
    typed_identity = cast("Mapping[str, object]", identity_values)
    if typed_identity.get("tenant_id") != scope.tenant_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "Skill repository parent identity does not match its tenant scope",
        )
    if scope.project_id is not None and typed_identity.get("project_id") != scope.project_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "Skill repository parent identity does not match its project scope",
        )
    identity = dict(typed_identity)

    operation = OperationContextV2(
        generation=parent_operation.generation,
        operation_id=f"{normalized_consumer}:{uuid4().hex}",
        scope=scope,
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(OPERATION_IDENTITY_SERVICE_V2, identity)
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "child-authority",
                "consumer": normalized_consumer,
                "parent_operation_id": parent_operation.operation_id,
            },
        )
        services: object = resolver.resolve(operation)
        if not isinstance(services, SkillRepositoryApplicationServicesV2):
            raise RuntimeV2Error(
                "invalid_skill_repository_application_services",
                "Skill repository resolver returned invalid application services",
            )
        repository: object = services.repository
        if not isinstance(repository, SkillRepositoryPort):
            raise RuntimeV2Error(
                "invalid_skill_repository",
                "Skill repository application services returned an invalid repository",
            )
        version_repository: object = services.version_repository
        if not isinstance(version_repository, SkillVersionRepositoryPort):
            raise RuntimeV2Error(
                "invalid_skill_version_repository",
                "Skill repository application services returned an invalid version repository",
            )
        yield SkillRepositoryOperationAuthorityV2(
            operation=operation,
            repository=repository,
            version_repository=version_repository,
        )


__all__ = [
    "SkillRepositoryOperationAuthorityV2",
    "skill_repository_child_operation_authority_v2",
]
