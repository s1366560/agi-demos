# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned Agent workflow status."""

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
from src.infrastructure.plugins.v2.agent_workflow_status_services import (
    AGENT_WORKFLOW_STATUS_SERVICE_V2,
    AgentWorkflowStatusServiceProtocolV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AgentWorkflowStatusHttpApplicationAuthorityV2:
    """Request-owned workflow status service and disposable operation."""

    operation: OperationContextV2
    db: AsyncSession
    service: AgentWorkflowStatusServiceProtocolV2


async def agent_workflow_status_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AgentWorkflowStatusHttpApplicationAuthorityV2]:
    """Yield workflow status from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-agent-workflow-status:{uuid4()}",
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
        service = operation.require(AGENT_WORKFLOW_STATUS_SERVICE_V2)
        if not isinstance(service, AgentWorkflowStatusServiceProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_workflow_status_service",
                "Agent workflow status service has an invalid implementation",
            )
        yield AgentWorkflowStatusHttpApplicationAuthorityV2(
            operation=operation,
            db=db,
            service=service,
        )


__all__ = [
    "AgentWorkflowStatusHttpApplicationAuthorityV2",
    "agent_workflow_status_http_application_authority_dependency_v2",
]
