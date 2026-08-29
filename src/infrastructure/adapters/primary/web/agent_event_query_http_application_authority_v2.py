# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned Agent event query services."""

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
from src.infrastructure.plugins.v2.agent_event_query_services import (
    AGENT_EVENT_QUERY_SERVICE_V2,
    AgentEventQueryResolverProtocolV2,
    AgentEventQueryServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AgentEventQueryHttpApplicationAuthorityV2:
    """Request-owned Agent event query service and disposable operation."""

    operation: OperationContextV2
    db: AsyncSession
    service: AgentEventQueryServiceV2


async def agent_event_query_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AgentEventQueryHttpApplicationAuthorityV2]:
    """Yield event query services from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-agent-event-query:{uuid4()}",
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
        resolver = operation.require(AGENT_EVENT_QUERY_SERVICE_V2)
        if not isinstance(resolver, AgentEventQueryResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_event_query_resolver",
                "Agent event query service has an invalid resolver",
            )
        yield AgentEventQueryHttpApplicationAuthorityV2(
            operation=operation,
            db=db,
            service=resolver.resolve(operation),
        )


__all__ = [
    "AgentEventQueryHttpApplicationAuthorityV2",
    "agent_event_query_http_application_authority_dependency_v2",
]
