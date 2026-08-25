# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned tenant skill configuration services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tenant_skill_config_services import (
    TENANT_SKILL_CONFIG_APPLICATION_SERVICE_V2,
    TenantSkillConfigApplicationResolverProtocolV2,
    TenantSkillConfigApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class TenantSkillConfigApplicationAuthorityV2:
    """Tenant request's immutable generation lease and repository set."""

    operation: OperationContextV2
    db: AsyncSession
    current_user: User
    tenant_id: str
    services: TenantSkillConfigApplicationServicesV2


@asynccontextmanager
async def tenant_skill_config_application_authority_context_v2(
    *,
    request: Request,
    current_user: User,
    tenant_id: str,
    db: AsyncSession,
) -> AsyncIterator[TenantSkillConfigApplicationAuthorityV2]:
    """Pin one generation and resolve tenant skill config services."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-tenant-skill-config:{uuid4()}",
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
        resolver = operation.require(TENANT_SKILL_CONFIG_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, TenantSkillConfigApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_tenant_skill_config_application_resolver",
                "tenant skill config application service has an invalid implementation",
            )
        yield TenantSkillConfigApplicationAuthorityV2(
            operation=operation,
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
            services=resolver.resolve(operation),
        )


__all__ = [
    "TenantSkillConfigApplicationAuthorityV2",
    "tenant_skill_config_application_authority_context_v2",
]
