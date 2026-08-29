# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned Agent SubAgent control."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    AGENT_SUBAGENT_CONTROL_SERVICE_V2,
    AgentSubAgentControlServiceProtocolV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class AgentSubAgentControlHttpApplicationAuthorityV2:
    """Request-owned SubAgent control service and disposable operation."""

    operation: OperationContextV2
    service: AgentSubAgentControlServiceProtocolV2


async def agent_subagent_control_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> AsyncIterator[AgentSubAgentControlHttpApplicationAuthorityV2]:
    """Yield SubAgent control from the generation pinned to this request."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-agent-subagent-control:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        service = operation.require(AGENT_SUBAGENT_CONTROL_SERVICE_V2)
        if not isinstance(service, AgentSubAgentControlServiceProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_subagent_control_service",
                "Agent SubAgent control service has an invalid implementation",
            )
        yield AgentSubAgentControlHttpApplicationAuthorityV2(
            operation=operation,
            service=service,
        )


__all__ = [
    "AgentSubAgentControlHttpApplicationAuthorityV2",
    "agent_subagent_control_http_application_authority_dependency_v2",
]
