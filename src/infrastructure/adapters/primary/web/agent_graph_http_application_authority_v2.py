# pyright: reportImportCycles=false, reportUnnecessaryIsInstance=false
"""FastAPI authority for generation-owned Agent graph management."""

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
from src.infrastructure.plugins.v2.agent_graph_management_services import (
    AGENT_GRAPH_MANAGEMENT_SERVICE_V2,
    AgentGraphManagementResolverProtocolV2,
    AgentGraphManagementServiceProtocolV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AgentGraphHttpApplicationAuthorityV2:
    """Request-owned graph service and disposable operation."""

    operation: OperationContextV2
    service: AgentGraphManagementServiceProtocolV2


async def agent_graph_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AgentGraphHttpApplicationAuthorityV2]:
    """Yield graph management from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-agent-graph-management:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _db_effect = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
        _identity_effect = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"user_id": str(current_user.id)},
        )
        _metadata_effect = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        resolver = operation.require(AGENT_GRAPH_MANAGEMENT_SERVICE_V2)
        if not isinstance(resolver, AgentGraphManagementResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_graph_management_resolver",
                "Agent graph management service has an invalid resolver",
            )
        service = resolver.resolve(operation)
        if not isinstance(service, AgentGraphManagementServiceProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_graph_management_service",
                "Agent graph management resolver returned an invalid service",
            )
        yield AgentGraphHttpApplicationAuthorityV2(
            operation=operation,
            service=service,
        )


__all__ = [
    "AgentGraphHttpApplicationAuthorityV2",
    "agent_graph_http_application_authority_dependency_v2",
]
