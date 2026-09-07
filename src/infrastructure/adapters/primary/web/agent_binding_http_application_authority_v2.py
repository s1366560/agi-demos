# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned tenant AgentBinding services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_binding_services import (
    AGENT_BINDING_SERVICE_V2,
    AgentBindingResolverProtocolV2,
    AgentBindingServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    bind_operation_context_v2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AgentBindingHttpApplicationAuthorityV2:
    """Request-owned AgentBinding service and disposable tenant operation."""

    operation: OperationContextV2
    db: AsyncSession
    tenant_id: str
    service: AgentBindingServiceV2


@asynccontextmanager
async def agent_binding_http_application_authority_v2(
    *,
    request: Request,
    current_user: User,
    tenant_id: str,
    db: AsyncSession,
) -> AsyncIterator[AgentBindingHttpApplicationAuthorityV2]:
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-agent-bindings:{uuid4()}",
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
        resolver = operation.require(AGENT_BINDING_SERVICE_V2)
        if not isinstance(resolver, AgentBindingResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_binding_resolver",
                "AgentBinding service has an invalid implementation",
            )
        with bind_operation_context_v2(operation):
            yield AgentBindingHttpApplicationAuthorityV2(
                operation=operation,
                db=db,
                tenant_id=tenant_id,
                service=resolver.resolve(operation),
            )


__all__ = [
    "AgentBindingHttpApplicationAuthorityV2",
    "agent_binding_http_application_authority_v2",
]
