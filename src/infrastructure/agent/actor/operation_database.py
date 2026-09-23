"""Own a fresh database session for each independently admitted agent turn."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.model.plugins.generated_v2 import ScopeV2
    from src.infrastructure.plugins.v2.runtime import OperationContextV2
    from src.infrastructure.plugins.v2.runtime_host import DataPlaneGenerationAdmissionV2


@asynccontextmanager
async def admit_agent_turn_v2(
    admission: DataPlaneGenerationAdmissionV2,
    *,
    descriptor_payload: Mapping[str, object] | None,
    distribution_payload: Mapping[str, object] | None,
    operation_id: str,
    scope: ScopeV2,
    services: Mapping[str, object] | None = None,
) -> AsyncIterator[OperationContextV2]:
    """Never carry the HTTP/WebSocket session into another task or worker process.

    The operation disposes its consumers before the session closes. Errors and cancellation
    roll back remaining work; individual application services own their explicit commits.
    """
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2

    async with (
        async_session_factory() as db,
        admission.admit(
            descriptor_payload=descriptor_payload,
            distribution_payload=distribution_payload,
            operation_id=operation_id,
            scope=scope,
            services={**(services or {}), OPERATION_DB_SESSION_SERVICE_V2: db},
        ) as operation,
    ):
        yield operation
