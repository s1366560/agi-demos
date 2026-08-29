# pyright: reportImportCycles=false, reportUnnecessaryIsInstance=false
"""FastAPI authority for generation-owned Skill repositories."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.skill_repository_services import (
    SKILL_REPOSITORY_APPLICATION_SERVICE_V2,
    SkillRepositoryApplicationResolverProtocolV2,
)


@dataclass(frozen=True, kw_only=True)
class SkillRepositoryHttpApplicationAuthorityV2:
    """Request-owned Skill repository and disposable operation."""

    operation: OperationContextV2
    db: AsyncSession
    repository: SkillRepositoryPort


@asynccontextmanager
async def skill_repository_http_application_authority_v2(
    *,
    request: Request,
    tenant_id: str,
    current_user: User,
    db: AsyncSession,
) -> AsyncIterator[SkillRepositoryHttpApplicationAuthorityV2]:
    """Yield a Skill repository from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-skill-repository:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant_id),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": tenant_id, "user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(SKILL_REPOSITORY_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, SkillRepositoryApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_repository_application_resolver",
                "Skill repository application service has an invalid resolver",
            )
        repository = resolver.resolve(operation).repository
        if not isinstance(repository, SkillRepositoryPort):
            raise RuntimeV2Error(
                "invalid_skill_repository",
                "Skill repository Provider returned an invalid repository",
            )
        yield SkillRepositoryHttpApplicationAuthorityV2(
            operation=operation,
            db=db,
            repository=repository,
        )


__all__ = [
    "SkillRepositoryHttpApplicationAuthorityV2",
    "skill_repository_http_application_authority_v2",
]
