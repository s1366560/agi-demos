# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned Agent execution resume."""

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
from src.infrastructure.plugins.v2.agent_execution_resume_services import (
    AGENT_EXECUTION_RESUME_SERVICE_V2,
    AgentExecutionResumeResolverProtocolV2,
    AgentExecutionResumeServiceProtocolV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AgentExecutionResumeHttpApplicationAuthorityV2:
    """Request-owned execution resume service and disposable operation."""

    operation: OperationContextV2
    db: AsyncSession
    service: AgentExecutionResumeServiceProtocolV2


async def agent_execution_resume_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AgentExecutionResumeHttpApplicationAuthorityV2]:
    """Yield execution resume from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-agent-execution-resume:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(AGENT_EXECUTION_RESUME_SERVICE_V2)
        if not isinstance(resolver, AgentExecutionResumeResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_execution_resume_resolver",
                "Agent execution resume service has an invalid resolver",
            )
        service = resolver.resolve(operation)
        if not isinstance(service, AgentExecutionResumeServiceProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_execution_resume_service",
                "Agent execution resume resolver returned an invalid service",
            )
        yield AgentExecutionResumeHttpApplicationAuthorityV2(
            operation=operation,
            db=db,
            service=service,
        )


__all__ = [
    "AgentExecutionResumeHttpApplicationAuthorityV2",
    "agent_execution_resume_http_application_authority_dependency_v2",
]
