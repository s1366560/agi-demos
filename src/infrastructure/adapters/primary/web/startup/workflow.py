"""Workflow engine initialization for startup."""

import logging
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select

from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, TaskLog
from src.infrastructure.adapters.secondary.workflow import AsyncioWorkflowEngine

logger = logging.getLogger(__name__)


async def _update_episode_processing_records(
    *,
    task_id: str | None,
    memory_id: str | None,
    status: str,
    progress: int,
    message: str,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    """Persist task and memory processing state for the episode workflow."""
    if not task_id and not memory_id:
        return

    now = datetime.now(UTC)
    async with async_session_factory() as session, session.begin():
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

        if memory_id:
            memory_result = await session.execute(
                refresh_select_statement(select(Memory).where(Memory.id == memory_id))
            )
            memory = memory_result.scalar_one_or_none()
            if memory is not None:
                memory.processing_status = status
                memory.updated_at = now


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


async def _project_exists(project_id: str) -> bool:
    async with async_session_factory() as session:
        result = await session.execute(
            refresh_select_statement(select(Project.id).where(Project.id == project_id).limit(1))
        )
        return result.scalar_one_or_none() is not None


async def _run_episode_processing_workflow(
    payload: dict[str, Any],
    graph_service: object,
) -> dict[str, object]:
    """Run local episode graph extraction for the asyncio workflow engine."""
    task_id = _read_optional_str(payload, "task_id")
    memory_id = _read_optional_str(payload, "memory_id")
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

    if project_id and not await _project_exists(project_id):
        message = f"Project {project_id} does not exist; cannot process episode"
        await _update_episode_processing_records(
            task_id=task_id,
            memory_id=memory_id,
            status="FAILED",
            progress=100,
            message="Graph processing failed",
            error_message=message,
        )
        raise ValueError(message)

    await _update_episode_processing_records(
        task_id=task_id,
        memory_id=memory_id,
        status="PROCESSING",
        progress=10,
        message="Extracting entities and relationships",
    )

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
        await _update_episode_processing_records(
            task_id=task_id,
            memory_id=memory_id,
            status="COMPLETED",
            progress=100,
            message="Graph processing complete",
            result=result_payload,
        )
        return result_payload
    except Exception as exc:
        await _update_episode_processing_records(
            task_id=task_id,
            memory_id=memory_id,
            status="FAILED",
            progress=100,
            message="Graph processing failed",
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
    except Exception as exc:
        await _update_episode_processing_records(
            task_id=task_id,
            memory_id=None,
            status="FAILED",
            progress=100,
            message="Community rebuild failed",
            error_message=str(exc),
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
            WHERE ep.uuid IN $episode_uuids
            RETURN ep.uuid as uuid, ep.content as content, ep.project_id as project_id,
                   ep.tenant_id as tenant_id, ep.user_id as user_id
            LIMIT $limit
            """,
            episode_uuids=episode_uuids,
            limit=limit,
        )
    else:
        result = await neo4j_client.execute_query(
            """
            MATCH (ep:Episodic)
            WHERE $project_id IS NULL OR ep.project_id = $project_id
            RETURN ep.uuid as uuid, ep.content as content, ep.project_id as project_id,
                   ep.tenant_id as tenant_id, ep.user_id as user_id
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
            await cast(Any, processor)(
                episode_uuid=episode_uuid,
                content=content,
                project_id=episode.get("project_id") or project_id,
                tenant_id=episode.get("tenant_id") or tenant_id,
                user_id=episode.get("user_id") or user_id,
                excluded_entity_types=None,
            )
            processed += 1

        communities_result: dict[str, object] | None = None
        if payload.get("rebuild_communities") and project_id:
            communities_result = await _rebuild_communities_for_project(graph_service, project_id)

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
    except Exception as exc:
        await _update_episode_processing_records(
            task_id=task_id,
            memory_id=None,
            status="FAILED",
            progress=100,
            message="Incremental refresh failed",
            error_message=str(exc),
        )
        raise


async def initialize_workflow_engine(
    graph_service: object | None = None,
) -> WorkflowEnginePort | None:
    """Initialize the asyncio-based workflow engine.

    Returns:
        WorkflowEnginePort instance.
    """
    logger.info("Initializing Asyncio Workflow Engine...")
    workflow_engine = AsyncioWorkflowEngine()
    if graph_service is not None:
        workflow_engine.register_handler(
            "episode_processing",
            lambda payload: _run_episode_processing_workflow(payload, graph_service),
        )
        workflow_engine.register_handler(
            "incremental_refresh",
            lambda payload: _run_incremental_refresh_workflow(payload, graph_service),
        )
        workflow_engine.register_handler(
            "rebuild_communities",
            lambda payload: _run_rebuild_communities_workflow(payload, graph_service),
        )
        logger.info(
            "Registered workflow handlers: episode_processing, incremental_refresh, "
            "rebuild_communities"
        )
    else:
        logger.warning(
            "Graph service unavailable; episode_processing workflow handler not registered"
        )
    logger.info("Asyncio Workflow Engine initialized")
    return workflow_engine
