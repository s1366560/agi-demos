"""Episode management API routes."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.domain.model.memory.episode import Episode, SourceType
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graphiti_client,
    get_workflow_engine,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/episodes", tags=["episodes"])


# --- Schemas ---


class EpisodeCreate(BaseModel):
    name: str | None = None  # Auto-generated if not provided
    content: str
    source_description: str | None = "text"
    episode_type: str | None = "text"
    metadata: dict[str, Any] | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None


class EpisodeResponse(BaseModel):
    id: str
    name: str
    content: str
    status: str
    created_at: str | None = None
    message: str | None = None
    task_id: str | None = None  # Task ID for SSE streaming
    workflow_id: str | None = None  # Temporal workflow ID


class EpisodeDetail(BaseModel):
    uuid: str
    name: str
    content: str
    source_description: str | None = None
    created_at: str | None = None
    valid_at: str | None = None
    tenant_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    status: str | None = None


# --- Endpoints ---


@router.post("/", response_model=EpisodeResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_episode(
    episode: EpisodeCreate,
    background: bool = Query(
        False, description="Process in background (returns task_id for SSE streaming)"
    ),
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> EpisodeResponse:
    """
    Create a new episode and ingest it into the knowledge graph.

    The episode will be processed using a hybrid approach:
    1. Immediate storage in DB
    2. Asynchronous processing for graph building:
       - Entity extraction
       - Relationship identification
       - Community detection and updates

    Set background=true for SSE streaming of task progress.
    """
    try:
        # Auto-generate name if missing
        if not episode.name:
            episode.name = episode.content[:50] + "..."

        # Create episode in Graphiti (let Graphiti generate the UUID)
        group_id = episode.project_id or "neo4j"  # Use "neo4j" for CE
        episode_uuid = str(uuid4())

        if background:
            # Background mode: Create task and return task_id for SSE streaming
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.models import TaskLog

            # Create task payload
            task_payload = {
                "uuid": episode_uuid,
                "group_id": group_id,
                "project_id": episode.project_id,
                "tenant_id": episode.tenant_id,
                "user_id": episode.user_id or str(current_user.id),
                "name": episode.name,
                "content": episode.content,
                "source_description": episode.source_description,
                "episode_type": episode.episode_type,
            }

            # Create TaskLog record
            task_id = str(uuid4())
            async with async_session_factory() as session, session.begin():
                task_log = TaskLog(
                    id=task_id,
                    group_id=group_id,
                    task_type="add_episode",
                    status="PENDING",
                    payload=task_payload,
                    entity_id=episode_uuid,
                    entity_type="episode",
                    created_at=datetime.now(UTC),
                )
                session.add(task_log)

            # Add task_id to payload for progress tracking
            task_payload["task_id"] = task_id

            # Start Temporal workflow
            workflow_id = f"episode-{episode_uuid}"

            await workflow_engine.start_workflow(
                workflow_name="episode_processing",
                workflow_id=workflow_id,
                input_data=task_payload,
                task_queue="default",
            )

            logger.info(
                f"Background episode task {task_id} created for episode {episode_uuid}, "
                f"workflow_id={workflow_id}"
            )

            # Build status message
            message = "Episode queued for background processing via Temporal"

            return EpisodeResponse(
                id=episode_uuid,
                name=episode.name,
                content=episode.content,
                status="queued",
                message=message,
                created_at=datetime.now(UTC).isoformat(),
                task_id=task_id,
                workflow_id=workflow_id,
            )
        else:
            # Synchronous mode: Process through the native graph service.
            try:
                source_type = SourceType(episode.episode_type or SourceType.TEXT.value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=_("Unsupported episode_type")) from exc

            graph_episode = Episode(
                id=episode_uuid,
                name=episode.name,
                content=episode.content,
                source_type=source_type,
                valid_at=datetime.now(UTC),
                metadata=episode.metadata or {},
                tenant_id=episode.tenant_id,
                project_id=episode.project_id,
                user_id=episode.user_id or str(current_user.id),
            )
            result = await graphiti_client.add_episode(graph_episode)
            result_id = getattr(result, "id", None)
            legacy_episode = getattr(result, "episode", None)
            legacy_id = getattr(legacy_episode, "uuid", None) if legacy_episode else None
            episode_uuid = (
                result_id
                if isinstance(result_id, str)
                else legacy_id
                if isinstance(legacy_id, str)
                else episode_uuid
            )

            logger.info(f"Episode created by user {current_user.id}: {episode_uuid}")

            return EpisodeResponse(
                id=episode_uuid,
                name=episode.name,
                content=episode.content,
                status="processing",
                message="Episode queued for ingestion",
                created_at=datetime.now(UTC).isoformat(),
            )

    except Exception as e:
        logger.error(f"Failed to create episode: {e}")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to create episode: {error}").format(error=str(e)),
        ) from e


@router.get("/by-name/{episode_name}", response_model=EpisodeDetail)
async def get_episode(
    episode_name: str,
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> EpisodeDetail:
    """
    Get episode details by name.
    """
    try:
        query = """
        MATCH (e:Episodic {name: $name})
        RETURN properties(e) as props
        """

        result = await graphiti_client.driver.execute_query(query, name=episode_name)

        if not result.records:
            raise HTTPException(status_code=404, detail=_("Episode not found"))

        props = result.records[0]["props"]

        return EpisodeDetail(
            uuid=props.get("uuid", ""),
            name=props.get("name", ""),
            content=props.get("content", ""),
            source_description=props.get("source_description"),
            created_at=props.get("created_at"),
            valid_at=props.get("valid_at"),
            tenant_id=props.get("tenant_id"),
            project_id=props.get("project_id"),
            user_id=props.get("user_id"),
            status=props.get("status", "unknown"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get episode: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/")
async def list_episodes(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    project_id: str | None = Query(None, description="Filter by project ID"),
    user_id: str | None = Query(None, description="Filter by user ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_desc: bool = Query(True, description="Sort descending if True"),
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    List episodes with filtering and pagination.
    """
    try:
        conditions = []
        if tenant_id:
            conditions.append("e.tenant_id = $tenant_id")
        if project_id:
            conditions.append("e.project_id = $project_id")
        if user_id:
            conditions.append("e.user_id = $user_id")

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Count
        count_query = f"MATCH (e:Episodic) {where_clause} RETURN count(e) as total"
        count_result = await graphiti_client.driver.execute_query(
            count_query, tenant_id=tenant_id, project_id=project_id, user_id=user_id
        )
        total = count_result.records[0]["total"] if count_result.records else 0

        # List
        order_clause = "DESC" if sort_desc else "ASC"
        list_query = f"""
        MATCH (e:Episodic)
        {where_clause}
        RETURN properties(e) as props
        ORDER BY e.{sort_by} {order_clause}
        SKIP $offset
        LIMIT $limit
        """

        result = await graphiti_client.driver.execute_query(
            list_query,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            offset=offset,
            limit=limit,
        )

        episodes = []
        for r in result.records:
            props = r["props"]
            episodes.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "content": props.get("content", ""),
                    "source_description": props.get("source_description"),
                    "created_at": props.get("created_at"),
                    "valid_at": props.get("valid_at"),
                    "tenant_id": props.get("tenant_id"),
                    "project_id": props.get("project_id"),
                    "user_id": props.get("user_id"),
                    "status": props.get("status", "unknown"),
                }
            )

        return {
            "episodes": episodes,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(episodes) < total,
        }

    except Exception as e:
        logger.error(f"Failed to list episodes: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/by-name/{episode_name}")
async def delete_episode(
    episode_name: str,
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Delete an episode and its relationships.

    Warning: This will permanently delete the episode and all
    associated relationships. Entities will be preserved.
    """
    try:
        query = """
        MATCH (e:Episodic {name: $name})
        DETACH DELETE e
        RETURN count(e) as deleted
        """

        result = await graphiti_client.driver.execute_query(query, name=episode_name)
        deleted = result.records[0]["deleted"] if result.records else 0

        if deleted == 0:
            raise HTTPException(status_code=404, detail=_("Episode not found"))

        return {"status": "success", "message": f"Episode '{episode_name}' deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete episode: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/health", response_model=dict)
async def health_check(
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Health check endpoint for episode service.
    """
    try:
        # Simple check - can we execute a query?
        await graphiti_client.driver.execute_query("RETURN 1 as test")
        return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=_("Service unhealthy: {error}").format(error=str(e)),
        ) from e
