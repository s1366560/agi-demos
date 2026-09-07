# pyright: reportImportCycles=false
"""FastAPI authority dependency for generation-owned Cron services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.cron_services import (
    CRON_APPLICATION_SERVICE_V2,
    CronApplicationResolverProtocolV2,
    CronApplicationServicesV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class CronApplicationAuthorityV2:
    """Request-owned Cron services and their disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    user_id: str
    services: CronApplicationServicesV2


async def cron_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[CronApplicationAuthorityV2]:
    """Yield Cron services from the generation pinned to this request."""
    user_id = str(current_user.id)
    project_id = _scope_id_v2(request.path_params.get("project_id"))
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-cron-application:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(OPERATION_IDENTITY_SERVICE_V2, {"user_id": user_id})
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "http-authority",
                "method": request.method,
                "path": request.url.path,
                "project_id": project_id,
            },
        )
        resolver = operation.require(CRON_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, CronApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_cron_application_resolver",
                "cron application service has an invalid implementation",
            )
        yield CronApplicationAuthorityV2(
            operation=operation,
            db=db,
            user_id=user_id,
            services=resolver.resolve(operation),
        )


def _scope_id_v2(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "CronApplicationAuthorityV2",
    "cron_application_authority_dependency_v2",
]
