"""Workflow engine initialization for startup."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any, cast

from sqlalchemy import select

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.domain.model.memory.processing import MemoryProcessingSource
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.background_tasks import TaskManager
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncTombstoneModel,
)
from src.infrastructure.adapters.secondary.persistence.memory_processing import (
    update_memory_processing_status,
)
from src.infrastructure.adapters.secondary.persistence.memory_processing_admission import (
    canonical_graph_tenant,
    legacy_graph_write,
    require_processing_source,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, TaskLog
from src.infrastructure.adapters.secondary.workflow import AsyncioWorkflowEngine
from src.infrastructure.plugins.v2.boundary import (
    current_process_generation_host_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.graph_runtime import (
    GRAPH_RUNTIME_SERVICE_V2,
    GraphRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

logger = logging.getLogger(__name__)

GraphWorkflowHandler = Callable[[dict[str, Any], object], Awaitable[dict[str, object]]]


async def _update_episode_processing_records(
    *,
    task_id: str | None,
    memory_id: str | None,
    status: str,
    progress: int,
    message: str,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
    processing_source: MemoryProcessingSource | None = None,
) -> bool:
    """Persist task and memory processing state for the episode workflow."""
    if not task_id and not memory_id:
        return True

    now = datetime.now(UTC)
    async with async_session_factory() as session, session.begin():
        if memory_id and (
            processing_source is None
            or processing_source.memory_id != memory_id
            or not await update_memory_processing_status(session, processing_source, status)
        ):
            return False
        if task_id:
            task_result = await session.execute(
                refresh_select_statement(select(TaskLog).where(TaskLog.id == task_id))
            )
            task = task_result.scalar_one_or_none()
            if task is not None:
                task.status = status
                task.progress = progress
                task.message = message
                task.error_message = error_message
                if result is not None:
                    task.result = result
                if status == "PROCESSING" and task.started_at is None:
                    task.started_at = now
                if status in {"COMPLETED", "FAILED"}:
                    task.completed_at = now

        return True


def _episode_processing_result(result: object, episode_uuid: str) -> dict[str, object]:
    """Build a compact, JSON-safe result payload for TaskLog consumers."""
    nodes = list(getattr(result, "nodes", []) or [])
    edges = list(getattr(result, "edges", []) or [])
    episodic_edges = list(getattr(result, "episodic_edges", []) or [])

    return {
        "episode_uuid": episode_uuid,
        "entities": len(nodes),
        "relationships": len(edges),
        "mentions": len(episodic_edges),
    }


def _read_optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


async def _run_episode_processing_workflow(
    payload: dict[str, Any],
    graph_service: object,
) -> dict[str, object]:
    """Run local episode graph extraction for the asyncio workflow engine."""
    task_id = _read_optional_str(payload, "task_id")
    memory_id = _read_optional_str(payload, "memory_id")
    processing_source = MemoryProcessingSource.from_payload(payload)
    episode_uuid = _read_optional_str(payload, "uuid")
    content = _read_optional_str(payload, "content")
    project_id = _read_optional_str(payload, "project_id")
    tenant_id = _read_optional_str(payload, "tenant_id")
    user_id = _read_optional_str(payload, "user_id")
    excluded_entity_types = payload.get("excluded_entity_types")

    if not episode_uuid or not content:
        raise ValueError("episode_processing workflow requires uuid and content")

    processor = getattr(graph_service, "process_episode", None)
    if not callable(processor):
        raise RuntimeError("Graph service does not support episode processing")

    admitted = False
    try:
        async with legacy_graph_write(
            async_session_factory,
            project_id=project_id,
            tenant_id=tenant_id,
            memory_id=memory_id,
        ) as admission:
            await require_processing_source(
                admission,
                processing_source,
                episode_uuid=episode_uuid,
                content=content,
            )
            tenant_id = await canonical_graph_tenant(admission, cast(str, project_id))
            applied = await _update_episode_processing_records(
                task_id=task_id,
                memory_id=memory_id,
                processing_source=processing_source,
                status="PROCESSING",
                progress=10,
                message="Extracting entities and relationships",
            )
            if not applied:
                raise KnowledgeSyncError("knowledge_sync_write_conflict")
            admitted = True
            try:
                result = await cast(Any, processor)(
                    episode_uuid=episode_uuid,
                    content=content,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    excluded_entity_types=cast(
                        list[str] | None,
                        excluded_entity_types if isinstance(excluded_entity_types, list) else None,
                    ),
                )
                result_payload = _episode_processing_result(result, episode_uuid)
                applied = await _update_episode_processing_records(
                    task_id=task_id,
                    memory_id=memory_id,
                    processing_source=processing_source,
                    status="COMPLETED",
                    progress=100,
                    message="Graph processing complete",
                    result=result_payload,
                )
                if not applied:
                    raise KnowledgeSyncError("knowledge_sync_write_conflict")
                return result_payload
            except (Exception, asyncio.CancelledError) as exc:
                applied = await _update_episode_processing_records(
                    task_id=task_id,
                    memory_id=memory_id,
                    processing_source=processing_source,
                    status="FAILED",
                    progress=100,
                    message="Graph processing failed",
                    error_message=str(exc) or "Graph processing cancelled",
                )
                if not applied:
                    await _update_episode_processing_records(
                        task_id=task_id,
                        memory_id=None,
                        status="FAILED",
                        progress=100,
                        message="Graph processing source rejected",
                        error_message=str(exc),
                    )
                raise
    except (Exception, asyncio.CancelledError) as exc:
        if not admitted:
            await _update_episode_processing_records(
                task_id=task_id,
                memory_id=None,
                status="FAILED",
                progress=100,
                message="Graph processing source rejected",
                error_message=str(exc),
            )
        raise


async def _rebuild_communities_for_project(
    graph_service: object,
    project_id: str,
) -> dict[str, object]:
    neo4j_client = getattr(graph_service, "_neo4j_client", None)
    if neo4j_client is None:
        raise RuntimeError("Graph service does not expose a Neo4j client")

    from src.infrastructure.graph.schemas import EntityNode

    await neo4j_client.execute_query(
        """
        MATCH (c:Community)
        WHERE c.project_id = $project_id OR c.group_id = $project_id
        DETACH DELETE c
        """,
        project_id=project_id,
    )

    entity_result = await neo4j_client.execute_query(
        """
        MATCH (e:Entity)
        WHERE e.project_id = $project_id
        RETURN e.uuid as uuid, e.name as name, e.entity_type as entity_type
        """,
        project_id=project_id,
    )

    entities = [
        EntityNode(
            uuid=record["uuid"],
            name=record["name"],
            entity_type=record.get("entity_type", "Entity"),
            project_id=project_id,
        )
        for record in entity_result.records
    ]

    communities_count = 0
    community_updater = getattr(graph_service, "community_updater", None)
    if community_updater is not None:
        communities = await community_updater.update_communities_for_entities(
            entities=entities,
            project_id=project_id,
            regenerate_all=True,
        )
        communities_count = len(communities) if communities else 0

    return {
        "project_id": project_id,
        "communities": communities_count,
        "entities": len(entities),
    }


async def _run_rebuild_communities_workflow(
    payload: dict[str, Any],
    graph_service: object,
) -> dict[str, object]:
    task_id = _read_optional_str(payload, "task_id")
    project_id = _read_optional_str(payload, "project_id") or _read_optional_str(
        payload, "task_group_id"
    )
    if not project_id:
        raise ValueError("rebuild_communities workflow requires project_id")

    await _update_episode_processing_records(
        task_id=task_id,
        memory_id=None,
        status="PROCESSING",
        progress=10,
        message="Rebuilding graph communities",
    )

    try:
        async with legacy_graph_write(
            async_session_factory,
            project_id=project_id,
            tenant_id=_read_optional_str(payload, "tenant_id"),
        ):
            result = await _rebuild_communities_for_project(graph_service, project_id)
            await _update_episode_processing_records(
                task_id=task_id,
                memory_id=None,
                status="COMPLETED",
                progress=100,
                message="Community rebuild complete",
                result=result,
            )
            return result

    except (Exception, asyncio.CancelledError) as exc:
        await _update_episode_processing_records(
            task_id=task_id,
            memory_id=None,
            status="FAILED",
            progress=100,
            message="Community rebuild failed",
            error_message=str(exc) or "Community rebuild cancelled",
        )
        raise


async def _load_incremental_refresh_episodes(
    graph_service: object,
    *,
    project_id: str | None,
    episode_uuids: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    neo4j_client = getattr(graph_service, "_neo4j_client", None)
    if neo4j_client is None:
        raise RuntimeError("Graph service does not expose a Neo4j client")

    if episode_uuids:
        result = await neo4j_client.execute_query(
            """
            MATCH (ep:Episodic)
            WHERE ep.uuid IN $episode_uuids AND ep.project_id = $project_id
            RETURN ep.uuid as uuid, ep.content as content, ep.project_id as project_id,
                   ep.tenant_id as tenant_id, ep.user_id as user_id, ep.memory_id as memory_id
            LIMIT $limit
            """,
            episode_uuids=episode_uuids,
            project_id=project_id,
            limit=limit,
        )
    else:
        result = await neo4j_client.execute_query(
            """
            MATCH (ep:Episodic)
            WHERE ep.project_id = $project_id
            RETURN ep.uuid as uuid, ep.content as content, ep.project_id as project_id,
                   ep.tenant_id as tenant_id, ep.user_id as user_id, ep.memory_id as memory_id
            ORDER BY ep.created_at DESC
            LIMIT $limit
            """,
            project_id=project_id,
            limit=limit,
        )

    return [dict(record) for record in result.records]


async def _run_incremental_refresh_workflow(
    payload: dict[str, Any],
    graph_service: object,
) -> dict[str, object]:
    task_id = _read_optional_str(payload, "task_id")
    project_id = _read_optional_str(payload, "project_id")
    tenant_id = _read_optional_str(payload, "tenant_id")
    user_id = _read_optional_str(payload, "user_id")
    raw_episode_uuids = payload.get("episode_uuids")
    episode_uuids = (
        [item for item in raw_episode_uuids if isinstance(item, str)]
        if isinstance(raw_episode_uuids, list)
        else None
    )

    processor = getattr(graph_service, "process_episode", None)
    if not callable(processor):
        raise RuntimeError("Graph service does not support episode processing")

    await _update_episode_processing_records(
        task_id=task_id,
        memory_id=None,
        status="PROCESSING",
        progress=10,
        message="Refreshing recent graph episodes",
    )

    try:
        async with legacy_graph_write(
            async_session_factory,
            project_id=project_id,
            tenant_id=tenant_id,
        ) as admission:
            tenant_id = await canonical_graph_tenant(admission, cast(str, project_id))
            episodes = await _load_incremental_refresh_episodes(
                graph_service,
                project_id=project_id,
                episode_uuids=episode_uuids,
                limit=100,
            )
            processed = 0
            skipped = 0
            for episode in episodes:
                episode_uuid = episode.get("uuid")
                content = episode.get("content")
                if not isinstance(episode_uuid, str) or not isinstance(content, str) or not content:
                    skipped += 1
                    continue
                if episode.get("project_id") != project_id or episode.get("tenant_id") != tenant_id:
                    raise KnowledgeSyncError("knowledge_sync_forbidden")
                source_id = episode.get("memory_id") or episode_uuid
                memory = await admission.get(Memory, source_id)
                if memory is not None:
                    if memory.project_id != project_id:
                        raise KnowledgeSyncError("knowledge_sync_forbidden")
                    content = memory.content
                elif episode.get("memory_id") or await admission.scalar(
                    select(KnowledgeSyncTombstoneModel.memory_id).where(
                        KnowledgeSyncTombstoneModel.memory_id == source_id
                    )
                ):
                    raise KnowledgeSyncError("knowledge_sync_write_conflict")
                await cast(Any, processor)(
                    episode_uuid=episode_uuid,
                    content=content,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    user_id=episode.get("user_id") or user_id,
                    excluded_entity_types=None,
                )
                processed += 1

            communities_result: dict[str, object] | None = None
            if payload.get("rebuild_communities") and project_id:
                communities_result = await _rebuild_communities_for_project(
                    graph_service, project_id
                )

            result: dict[str, object] = {
                "project_id": project_id,
                "processed": processed,
                "skipped": skipped,
                "communities": communities_result,
            }
            await _update_episode_processing_records(
                task_id=task_id,
                memory_id=None,
                status="COMPLETED",
                progress=100,
                message="Incremental refresh complete",
                result=result,
            )
            return result

    except (Exception, asyncio.CancelledError) as exc:
        await _update_episode_processing_records(
            task_id=task_id,
            memory_id=None,
            status="FAILED",
            progress=100,
            message="Incremental refresh failed",
            error_message=str(exc) or "Incremental refresh cancelled",
        )
        raise


async def _run_with_graph_runtime_v2(
    handler: GraphWorkflowHandler,
    payload: dict[str, Any],
) -> dict[str, object]:
    """Run one background workflow against its own immutable generation lease."""
    host = current_process_generation_host_v2()
    async with pin_generation_v2(host) as generation:
        runtime = generation.resolve(
            GRAPH_RUNTIME_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        if not isinstance(runtime, GraphRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_graph_runtime",
                "workflow generation has an invalid graph runtime service",
            )
        return await handler(payload, runtime.require())


def register_workflow_handlers_v2(
    workflow_engine: AsyncioWorkflowEngine,
) -> AsyncioWorkflowEngine:
    """Register the builtin handlers selected by the explicit V2 workflow module."""
    workflow_engine.register_handler(
        "episode_processing",
        partial(_run_with_graph_runtime_v2, _run_episode_processing_workflow),
    )
    workflow_engine.register_handler(
        "incremental_refresh",
        partial(_run_with_graph_runtime_v2, _run_incremental_refresh_workflow),
    )
    workflow_engine.register_handler(
        "rebuild_communities",
        partial(_run_with_graph_runtime_v2, _run_rebuild_communities_workflow),
    )
    logger.info(
        "Registered generation-leased workflow handlers: episode_processing, "
        "incremental_refresh, rebuild_communities"
    )
    return workflow_engine


def build_asyncio_workflow_engine_v2(*, manager: TaskManager) -> AsyncioWorkflowEngine:
    """Build the local workflow engine activated by the V2 Provider effect."""
    logger.info("Initializing Asyncio Workflow Engine...")
    workflow_engine = register_workflow_handlers_v2(AsyncioWorkflowEngine(manager=manager))
    logger.info("Asyncio Workflow Engine initialized")
    return workflow_engine
