"""Lease the admitted project graph for both stages of one durable indexing job."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import TYPE_CHECKING, Any

from src.application.services import memory_update_runtime
from src.infrastructure.adapters.primary.web.startup.project_graph_lease import project_graph_lease

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.application.services.memory_update_jobs import AcquireStages, JobStage

    from .scoped_profile_runtime_v2 import ScopedProfileRuntimeV2


def scoped_memory_update_stages(
    sessions: Callable[[], AsyncSession],
    runtime: ScopedProfileRuntimeV2,
) -> AcquireStages:
    @asynccontextmanager
    async def acquire(payload: dict[str, Any]) -> AsyncIterator[tuple[JobStage, JobStage]]:
        async with project_graph_lease(
            sessions, runtime, payload, actor_id=payload.get("user_id")
        ) as (scope, graph):
            admitted_payload = {**payload, "tenant_id": scope.tenant_id}
            yield (
                partial(
                    memory_update_runtime.extract_with_graph, admitted_payload, graph_service=graph
                ),
                partial(
                    memory_update_runtime.index_with_session,
                    admitted_payload,
                    session_factory=sessions,
                    embedding_service=getattr(graph, "embedder", None),
                ),
            )

    return acquire
