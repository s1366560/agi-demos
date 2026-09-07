# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned Agent execution query services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.agent_execution_query_services import (
    AGENT_EXECUTION_QUERY_SERVICE_V2,
    AgentExecutionQueryApplicationServicesV2,
    AgentExecutionQueryResolverProtocolV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AgentExecutionQueryApplicationAuthorityV2:
    """Request-owned execution queries and their disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    services: AgentExecutionQueryApplicationServicesV2


async def agent_execution_query_application_authority_dependency_v2(
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AgentExecutionQueryApplicationAuthorityV2]:
    """Yield execution query services from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-agent-execution-query:{uuid4()}",
        scope=ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {
                "tenant_id": tenant_id,
                "user_id": str(current_user.id),
                "project_id": project_id,
            },
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(AGENT_EXECUTION_QUERY_SERVICE_V2)
        if not isinstance(resolver, AgentExecutionQueryResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_execution_query_resolver",
                "Agent execution query service has an invalid resolver",
            )
        yield AgentExecutionQueryApplicationAuthorityV2(
            operation=operation,
            db=db,
            services=resolver.resolve(operation),
        )


__all__ = [
    "AgentExecutionQueryApplicationAuthorityV2",
    "agent_execution_query_application_authority_dependency_v2",
]
