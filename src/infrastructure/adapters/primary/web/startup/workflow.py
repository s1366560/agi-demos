"""Workflow engine initialization for startup."""

import logging
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select

from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import Memory, TaskLog
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
        logger.info("Registered episode_processing workflow handler")
    else:
        logger.warning(
            "Graph service unavailable; episode_processing workflow handler not registered"
        )
    logger.info("Asyncio Workflow Engine initialized")
    return workflow_engine
