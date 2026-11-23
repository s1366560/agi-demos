"""Acquire and retain the SQL-confirmed project graph for a background operation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from src.application.services.memory_update_jobs import GraphNotReady, MemoryUpdateJobError
from src.application.services.scoped_profile_initialization_service_v2 import (
    ScopedProfileInitializationV2Error,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import Project
from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import AGENT_TURN_REQUIRED_SERVICES_V2
from src.infrastructure.plugins.v2.graph_runtime import (
    GRAPH_RUNTIME_SERVICE_V2,
    GraphRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.domain.ports.services.graph_store_port import GraphStorePort

    from .scoped_profile_runtime_v2 import ScopedProfileRuntimeV2


@asynccontextmanager
async def project_graph_lease(
    sessions: Callable[[], AsyncSession],
    runtime: ScopedProfileRuntimeV2,
    payload: dict[str, Any],
    *,
    actor_id: str | None,
) -> AsyncIterator[tuple[ScopeV2, GraphStorePort]]:
    project_id = payload.get("project_id")
    async with sessions() as session:
        tenant_id = await session.scalar(select(Project.tenant_id).where(Project.id == project_id))
    if not tenant_id or payload.get("tenant_id") not in (tenant_id, None, ""):
        raise MemoryUpdateJobError("memory_update_project_scope_mismatch")
    scope = ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=tenant_id, project_id=project_id)
    try:
        try:
            reservation = await runtime.acquire(scope)
        except RuntimeV2Error as exc:
            if exc.code != "scope_recovery_unavailable":
                raise
            if not actor_id:
                raise GraphNotReady("project initialization requires a workflow actor") from exc
            # A first job can precede any project-level operation. Use the identical
            # project composition that instance management publishes at this revision.
            publication = await runtime.prepare_current(
                scope,
                actor_id=actor_id,
                required_services=AGENT_TURN_REQUIRED_SERVICES_V2,
            )
            if not publication.publication.accepted:
                raise GraphNotReady("project generation unavailable") from exc
            reservation = await runtime.acquire(scope)
    except (RuntimeV2Error, ScopedProfileInitializationV2Error) as exc:
        raise GraphNotReady("project generation unavailable") from exc

    try:
        reservation.claim()
        if reservation.scope != scope:
            raise MemoryUpdateJobError("memory_update_reservation_scope_mismatch")
        try:
            binding = reservation.lease.generation.resolve(GRAPH_RUNTIME_SERVICE_V2, scope)
        except RuntimeV2Error as exc:
            raise GraphNotReady("project generation has no graph") from exc
        if not isinstance(binding, GraphRuntimeServiceV2) or not binding.available:
            raise GraphNotReady("graph unavailable in admitted project generation")
        graph = binding.require()
        yield scope, graph
    finally:
        await reservation.lease.release()
