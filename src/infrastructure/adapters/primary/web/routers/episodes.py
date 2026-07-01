"""Episode management API routes."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.memory.episode import Episode, SourceType
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graph_store,
    get_workflow_engine,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/episodes", tags=["episodes"])

EPISODE_SORT_FIELDS = frozenset({"created_at", "valid_at", "name"})


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


async def _resolve_episode_scope(
    *,
    db: AsyncSession,
    current_user: User,
    default_tenant_id: str | None,
    requested_tenant_id: str | None,
    requested_project_id: str | None,
) -> tuple[str, str | None]:
    tenant_id = requested_tenant_id or default_tenant_id
    if tenant_id is None and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("User does not belong to any tenant. Please contact administrator."),
        )
    if requested_project_id is None:
        if (
            requested_tenant_id
            and default_tenant_id is not None
            and requested_tenant_id != default_tenant_id
            and not current_user.is_superuser
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_("Access denied to tenant"),
            )
        return tenant_id or requested_tenant_id or "neo4j", None

    if tenant_id is None and current_user.is_superuser:
        project_result = await db.execute(
            refresh_select_statement(select(Project).where(Project.id == requested_project_id))
        )
    else:
        project_result = await db.execute(
            refresh_select_statement(
                select(Project).where(
                    and_(Project.id == requested_project_id, Project.tenant_id == tenant_id)
                )
            )
        )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Project not found"))

    if current_user.is_superuser:
        return project.tenant_id or tenant_id or "neo4j", requested_project_id

    membership_result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                and_(
                    UserProject.user_id == current_user.id,
                    UserProject.project_id == requested_project_id,
                )
            )
        )
    )
    if not membership_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Access denied to project")
        )

    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("User does not belong to any tenant. Please contact administrator."),
        )
    return tenant_id, requested_project_id


async def _get_default_episode_tenant_id(db: AsyncSession, current_user: User) -> str | None:
    result = await db.execute(
        refresh_select_statement(
            select(UserTenant.tenant_id).where(UserTenant.user_id == current_user.id).limit(1)
        )
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id:
        return str(tenant_id)
    if current_user.is_superuser:
        return None
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("User does not belong to any tenant. Please contact administrator."),
    )


# --- Endpoints ---


@router.post("/", response_model=EpisodeResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_episode(
    episode: EpisodeCreate,
    background: bool = Query(
        False, description="Process in background (returns task_id for SSE streaming)"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
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
        default_tenant_id = await _get_default_episode_tenant_id(db, current_user)
        resolved_tenant_id, resolved_project_id = await _resolve_episode_scope(
            db=db,
            current_user=current_user,
            default_tenant_id=default_tenant_id,
            requested_tenant_id=episode.tenant_id,
            requested_project_id=episode.project_id,
        )
        actor_user_id = str(current_user.id)
        group_id = resolved_project_id or "neo4j"  # Use "neo4j" for CE
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
                "project_id": resolved_project_id,
                "tenant_id": resolved_tenant_id,
                "user_id": actor_user_id,
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
                tenant_id=resolved_tenant_id,
                project_id=resolved_project_id,
                user_id=actor_user_id,
            )
            if graph_store is None:
                raise HTTPException(status_code=503, detail=_("Graph backend unavailable"))
            result = await graph_store.add_episode(graph_episode)
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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to create episode")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to create episode"),
        ) from e


@router.get("/by-name/{episode_name}", response_model=EpisodeDetail)
async def get_episode(
    episode_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> EpisodeDetail:
    """
    Get episode details by name.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend unavailable"))
        tenant_id = await _get_default_episode_tenant_id(db, current_user)
        project_ids: list[str] = []
        if not current_user.is_superuser:
            project_result = await db.execute(
                refresh_select_statement(
                    select(UserProject.project_id).where(UserProject.user_id == current_user.id)
                )
            )
            project_ids = list(project_result.scalars().all())

        props = await graph_store.get_episode_by_name(
            episode_name,
            tenant_id=tenant_id,
            project_ids=project_ids if not current_user.is_superuser else None,
        )

        if not props:
            raise HTTPException(status_code=404, detail=_("Episode not found"))

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
        raise HTTPException(status_code=500, detail=_("Failed to get episode")) from e


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
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    List episodes with filtering and pagination.
    """
    try:
        if sort_by not in EPISODE_SORT_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("Invalid sort field"),
            )
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend unavailable"))

        default_tenant_id = await _get_default_episode_tenant_id(db, current_user)
        resolved_tenant_id, resolved_project_id = await _resolve_episode_scope(
            db=db,
            current_user=current_user,
            default_tenant_id=default_tenant_id,
            requested_tenant_id=tenant_id,
            requested_project_id=project_id,
        )

        # Resolve the caller's accessible project set when scoping is needed.
        store_project_ids: list[str] | None = None
        if resolved_project_id:
            # Single explicit project filter handled by project_id below.
            pass
        elif not current_user.is_superuser:
            project_result = await db.execute(
                refresh_select_statement(
                    select(UserProject.project_id).where(UserProject.user_id == current_user.id)
                )
            )
            store_project_ids = list(project_result.scalars().all())

        # Match the legacy condition behavior: tenant filter applied except for
        # the superuser-with-no-explicit-tenant/project default case.
        store_tenant_id: str | None = resolved_tenant_id
        if (
            resolved_tenant_id == "neo4j"
            and not tenant_id
            and not project_id
            and current_user.is_superuser
        ):
            store_tenant_id = None

        page = await graph_store.list_episodes(
            tenant_id=store_tenant_id,
            project_id=resolved_project_id or None,
            project_ids=store_project_ids,
            user_id=user_id,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )
        episodes = [
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
            for props in page["episodes"]
        ]
        total = page["total"]

        return {
            "episodes": episodes,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(episodes) < total,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list episodes: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to list episodes")) from e


@router.delete("/by-name/{episode_name}")
async def delete_episode(
    episode_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Delete an episode and its relationships.

    Warning: This will permanently delete the episode and all
    associated relationships. Entities will be preserved.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend unavailable"))
        tenant_id = await _get_default_episode_tenant_id(db, current_user)
        project_ids: list[str] = []
        if not current_user.is_superuser:
            project_result = await db.execute(
                refresh_select_statement(
                    select(UserProject.project_id).where(UserProject.user_id == current_user.id)
                )
            )
            project_ids = list(project_result.scalars().all())

        deleted = await graph_store.delete_episode_by_name(
            episode_name,
            tenant_id=tenant_id,
            project_ids=project_ids if not current_user.is_superuser else None,
        )

        if deleted == 0:
            raise HTTPException(status_code=404, detail=_("Episode not found"))

        return {"status": "success", "message": f"Episode '{episode_name}' deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete episode: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to delete episode")) from e


@router.get("/health", response_model=dict)
async def health_check(
    current_user: User = Depends(get_current_user),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Health check endpoint for episode service.
    """
    try:
        if graph_store is None or not await graph_store.health_probe():
            raise HTTPException(status_code=503, detail=_("Service unhealthy"))
        return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}
    except Exception as e:
        logger.exception("Episode service health check failed")
        raise HTTPException(
            status_code=503,
            detail=_("Service unhealthy"),
        ) from e
