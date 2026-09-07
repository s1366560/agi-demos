# pyright: reportImportCycles=false
"""FastAPI authority dependency for generation-owned task-log services."""

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
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.task_log_services import (
    TASK_LOG_APPLICATION_SERVICE_V2,
    TaskLogApplicationResolverProtocolV2,
    TaskLogApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class TaskLogApplicationAuthorityV2:
    """Request-owned task-log use cases and their operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    services: TaskLogApplicationServicesV2


async def task_log_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[TaskLogApplicationAuthorityV2]:
    """Yield task-log services from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-task-log-application:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": None, "user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(TASK_LOG_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, TaskLogApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_task_log_application_resolver",
                "task log application service has an invalid implementation",
            )
        yield TaskLogApplicationAuthorityV2(
            operation=operation,
            db=db,
            services=resolver.resolve(operation),
        )


__all__ = [
    "TaskLogApplicationAuthorityV2",
    "task_log_application_authority_dependency_v2",
]
