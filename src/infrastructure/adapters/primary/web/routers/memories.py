"""Memories API endpoints."""

import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.ports.services.graph_service_port import GraphServicePort
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graph_service,
    get_graphiti_client,
    get_workflow_engine,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)


async def _background_index_memory(
    memory_id: str,
    content: str,
    project_id: str,
    category: str = "other",
    metadata: dict[str, Any] | None = None,
    graph_service: GraphServicePort | None = None,
    session_factory: Any | None = None,
) -> None:
    """Index a memory's content as chunks in the background."""
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
            SqlChunkRepository,
        )
        from src.infrastructure.memory.chunk_sync import (
            normalize_memory_chunk_category,
            upsert_memory_chunks,
        )

        if session_factory is None:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory as default_session_factory,
            )

            session_factory = default_session_factory
        if session_factory is None:
            raise RuntimeError("Background memory indexing requires a session factory")

        embedding_service = getattr(graph_service, "embedder", None) if graph_service else None
        async with session_factory() as session:
            chunk_repo = SqlChunkRepository(session)
            indexed = await upsert_memory_chunks(
                chunk_repo,
                memory_id=memory_id,
                content=content,
                project_id=project_id,
                category=normalize_memory_chunk_category(category),
                metadata=metadata,
                embedding_service=embedding_service,
            )
            await session.commit()
            logger.info(f"Indexed {indexed} memory chunks for memory {memory_id}")
    except Exception as e:
        logger.warning(f"Background memory indexing failed for {memory_id}: {e}")


async def _delete_memory_chunks_for_request(
    db: AsyncSession,
    memory_id: str,
    project_id: str,
) -> int:
    """Delete a memory's chunks using the shared sync helper."""
    from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
        SqlChunkRepository,
    )
    from src.infrastructure.memory.chunk_sync import delete_memory_chunks

    chunk_repo = SqlChunkRepository(db)
    return await delete_memory_chunks(
        chunk_repo,
        memory_id=memory_id,
        project_id=project_id,
    )


def _build_request_session_factory(
    db: AsyncSession,
) -> async_sessionmaker[AsyncSession]:
    """Build a background-safe session factory from the current request engine."""
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


async def _get_memory_write_project(
    project_id: str,
    current_user: User,
    db: AsyncSession,
) -> Project:
    """Load a project after verifying the current user can create memories in it."""
    membership_result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
            )
        )
    )
    user_project = membership_result.scalar_one_or_none()

    project_result = await db.execute(
        refresh_select_statement(select(Project).where(Project.id == project_id))
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Project not found"))

    if user_project is None:
        if project.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_("You do not have access to this project"),
            )
        return cast(Project, project)

    if user_project.role == "viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Viewers cannot create memories"),
        )

    return cast(Project, project)


async def _verify_memory_read_access(
    memory: Memory,
    current_user: User,
    db: AsyncSession,
) -> None:
    """Require that the current user can read the memory's project."""
    membership_result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                UserProject.user_id == current_user.id,
                UserProject.project_id == memory.project_id,
            )
        )
    )
    if membership_result.scalar_one_or_none():
        return

    project_result = await db.execute(
        refresh_select_statement(select(Project).where(Project.id == memory.project_id))
    )
    project = project_result.scalar_one_or_none()
    if project is not None and (project.owner_id == current_user.id or project.is_public):
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_("Access denied"))


async def _has_memory_share_edit_permission(
    memory_id: str,
    user_id: str,
    db: AsyncSession,
) -> bool:
    """Return whether a direct memory share grants edit permission."""
    share_result = await db.execute(
        refresh_select_statement(
            select(MemoryShare).where(
                MemoryShare.memory_id == memory_id,
                MemoryShare.shared_with_user_id == user_id,
            )
        )
    )
    return any(
        (share.permissions or {}).get("edit") is True for share in share_result.scalars().all()
    )


async def _has_project_admin_access(
    memory: Memory,
    current_user: User,
    db: AsyncSession,
) -> bool:
    """Return whether the user can administer a memory through its project or tenant."""
    if current_user.is_superuser:
        return True

    project_result = await db.execute(
        refresh_select_statement(select(Project).where(Project.id == memory.project_id))
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        return False

    if project.owner_id == current_user.id:
        return True

    user_project_result = await db.execute(
        refresh_select_statement(
            select(UserProject.id).where(
                UserProject.user_id == current_user.id,
                UserProject.project_id == memory.project_id,
                UserProject.role.in_(["owner", "admin"]),
            )
        )
    )
    if user_project_result.scalar_one_or_none():
        return True

    tenant_role_result = await db.execute(
        refresh_select_statement(
            select(UserTenant.id).where(
                UserTenant.user_id == current_user.id,
                UserTenant.tenant_id == project.tenant_id,
                UserTenant.role.in_(["owner", "admin"]),
            )
        )
    )
    return tenant_role_result.scalar_one_or_none() is not None


async def _resolve_extraction_input(
    payload: dict[str, Any],
    current_user: User,
    db: AsyncSession,
) -> tuple[str, str | None, str | None]:
    """Resolve extraction text and scope from direct content/text or an accessible memory."""
    content = payload.get("content")
    if content is None:
        content = payload.get("text")
    if isinstance(content, str) and content:
        project_id = payload.get("project_id")
        tenant_id = payload.get("tenant_id")
        return (
            content,
            project_id if isinstance(project_id, str) else None,
            tenant_id if isinstance(tenant_id, str) else None,
        )

    memory_id = payload.get("memory_id")
    if not isinstance(memory_id, str) or not memory_id:
        return "", None, None

    result = await db.execute(
        refresh_select_statement(select(Memory).where(Memory.id == memory_id))
    )
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Memory not found"))

    await _verify_memory_read_access(cast(Memory, mem), current_user, db)
    memory = cast(Memory, mem)
    project_result = await db.execute(
        refresh_select_statement(select(Project).where(Project.id == memory.project_id))
    )
    project = project_result.scalar_one_or_none()
    return memory.content or "", memory.project_id, getattr(project, "tenant_id", None)


router = APIRouter(prefix="/api/v1", tags=["memories"])

# --- Schemas ---


class EntityCreate(BaseModel):
    name: str
    type: str
    description: str | None = None


class RelationshipCreate(BaseModel):
    source: str
    target: str
    type: str
    description: str | None = None


class MemoryCreate(BaseModel):
    project_id: str
    title: str
    content: str
    content_type: str = "text"
    tags: list[str] = []
    entities: list[EntityCreate] = []
    relationships: list[RelationshipCreate] = []
    collaborators: list[str] = []
    is_public: bool = False
    metadata: dict[str, Any] = {}


class MemoryResponse(BaseModel):
    id: str
    project_id: str
    title: str
    content: str
    content_type: str
    tags: list[str]
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    version: int
    author_id: str
    collaborators: list[str]
    is_public: bool
    status: str
    processing_status: str
    meta: dict[str, Any] = Field(serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime | None
    task_id: str | None = None  # Task ID for SSE streaming

    class Config:
        from_attributes = True


class MemoryListResponse(BaseModel):
    memories: list[MemoryResponse]
    total: int
    page: int
    page_size: int


class MemoryUpdate(BaseModel):
    """Schema for updating an existing memory."""

    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    entities: list[dict[str, Any]] | None = None
    relationships: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    version: int  # Required for optimistic locking


# --- Endpoints ---
@router.post("/memories/extract-entities")
async def extract_entities(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
) -> dict[str, Any]:
    content, project_id, tenant_id = await _resolve_extraction_input(payload, current_user, db)
    extractor = getattr(graph_service, "extract_entities", None)
    if graph_service is None or not callable(extractor):
        raise HTTPException(status_code=503, detail=_("Graph extraction service not available"))

    try:
        entities = await cast(Any, extractor)(
            content=content,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=str(current_user.id),
        )
    except Exception as e:
        logger.error("Entity extraction failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=_("Failed to extract entities")) from e

    return {"entities": entities, "source": "knowledge_graph"}


@router.post("/memories/extract-relationships")
async def extract_relationships(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
) -> dict[str, Any]:
    content, project_id, tenant_id = await _resolve_extraction_input(payload, current_user, db)
    extractor = getattr(graph_service, "extract_relationships", None)
    if graph_service is None or not callable(extractor):
        raise HTTPException(status_code=503, detail=_("Graph extraction service not available"))

    entities = payload.get("entities")
    try:
        relationships = await cast(Any, extractor)(
            content=content,
            entities=entities if isinstance(entities, list) else None,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=str(current_user.id),
        )
    except Exception as e:
        logger.error("Relationship extraction failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=_("Failed to extract relationships")) from e

    return {"relationships": relationships, "source": "knowledge_graph"}


@router.post("/memories/", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    memory_data: MemoryCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any = Depends(get_graphiti_client),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> Any:
    """Create a new memory.

    This endpoint stores memory using a hybrid approach:
    1. Immediate storage in DB
    2. Asynchronous graph building via Graphiti for relationship extraction
    """
    try:
        project_id = memory_data.project_id
        task_session_factory = _build_request_session_factory(db)
        project = await _get_memory_write_project(project_id, current_user, db)

        # Create memory
        memory_id = str(uuid4())

        memory = Memory(
            id=memory_id,
            project_id=project_id,
            title=memory_data.title,
            content=memory_data.content,
            content_type=memory_data.content_type,
            tags=memory_data.tags,
            entities=[e.dict() for e in memory_data.entities],
            relationships=[r.dict() for r in memory_data.relationships],
            author_id=current_user.id,
            collaborators=memory_data.collaborators,
            is_public=memory_data.is_public,
            meta=memory_data.metadata,
            version=1,
            status="ENABLED",
            processing_status="PENDING",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        db.add(memory)

        # 2. Add to Graphiti for graph building (async)
        try:
            # Pre-create EpisodicNode in Neo4j to avoid race conditions
            await graphiti_client.driver.execute_query(
                """
                MERGE (e:Episodic {uuid: $uuid})
                SET e:Node,
                    e.name = $name,
                    e.content = $content,
                    e.source_description = $source_description,
                    e.source = $source,
                    e.created_at = datetime($created_at),
                    e.valid_at = datetime($created_at),
                    e.group_id = $group_id,
                    e.tenant_id = $tenant_id,
                    e.project_id = $project_id,
                    e.user_id = $user_id,
                    e.memory_id = $memory_id,
                    e.status = 'Processing',
                    e.entity_edges = []
                """,
                uuid=memory.id,
                name=memory.title or str(memory.id),
                content=memory.content,
                source_description="User input",
                source="text",
                created_at=memory.created_at.isoformat(),
                group_id=project_id,
                tenant_id=project.tenant_id,
                project_id=project_id,
                user_id=current_user.id,
                memory_id=memory.id,
            )

            # Submit to Temporal workflow for processing
            from src.infrastructure.adapters.secondary.persistence.models import TaskLog

            task_id = str(uuid4())
            task_payload = {
                "group_id": project_id,
                "name": memory.title or str(memory.id),
                "content": memory.content,
                "source_description": "User input",
                "episode_type": "text",
                "entity_types": None,
                "uuid": memory.id,
                "tenant_id": project.tenant_id,
                "project_id": project_id,
                "user_id": str(current_user.id),
                "memory_id": memory.id,
            }

            # Create TaskLog record
            async with task_session_factory() as task_session, task_session.begin():
                task_log = TaskLog(
                    id=task_id,
                    group_id=project_id,
                    task_type="add_episode",
                    status="PENDING",
                    payload=task_payload,
                    entity_type="episode",
                    created_at=datetime.now(UTC),
                )
                task_session.add(task_log)

            task_payload["task_id"] = task_id

            # Start Temporal workflow
            workflow_id = f"episode-{memory.id}"
            await workflow_engine.start_workflow(
                workflow_name="episode_processing",
                workflow_id=workflow_id,
                input_data=task_payload,
                task_queue="default",
            )
            logger.info(f"Memory {memory.id} submitted to Temporal workflow {workflow_id}")

            # Add task_id to memory object for response
            memory.task_id = task_id
        except Exception as e:
            logger.error(f"Failed to add memory to queue: {e}", exc_info=True)
            # NOTE:
            #   At this point, any graph/Neo4j Episodic node that may have been
            #   created for this memory is not rolled back. If queueing fails,
            #   the memory record in the primary database is marked as FAILED
            #   (see fields below), but the corresponding Episodic node may
            #   remain in Neo4j as an orphan. This is a known limitation and
            #   may be addressed in the future by:
            #     1) moving Neo4j node creation into the queue worker so it is
            #        atomic with processing, or
            #     2) performing explicit cleanup of any already-created
            #        Episodic node when queueing fails.
            #
            # Mark memory as failed so user knows processing didn't start
            memory.processing_status = "FAILED"
            memory.processing_error = f"Failed to queue for processing: {e!s}"  # type: ignore[attr-defined]  # ORM field exists at runtime

        await db.commit()
        await db.refresh(memory)

        # Auto-index memory content as chunks (non-blocking)
        background_tasks.add_task(
            _background_index_memory,
            memory_id=memory.id,
            content=memory_data.content,
            project_id=project_id,
            category=(memory.meta or {}).get("category", "other"),
            metadata=memory.meta,
            graph_service=graph_service,
            session_factory=task_session_factory,
        )

        return MemoryResponse.from_orm(memory)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating memory")
        raise HTTPException(status_code=500, detail=_("Failed to create memory")) from e


@router.get("/memories/", response_model=MemoryListResponse)
async def list_memories(
    project_id: str = Query(..., description="Project ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str | None = Query(None, description="Search query"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryListResponse:
    """List memories for a project."""
    # Verify access
    user_project_result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
            )
        )
    )
    if not user_project_result.scalar_one_or_none():
        # Check ownership
        project_result = await db.execute(
            refresh_select_statement(select(Project).where(Project.id == project_id))
        )
        project = project_result.scalar_one_or_none()
        if not project or (project.owner_id != current_user.id and not project.is_public):
            raise HTTPException(status_code=403, detail=_("Access denied"))

    # Build query
    query = select(Memory).where(Memory.project_id == project_id)

    if search:
        query = query.where(
            or_(
                Memory.title.ilike(f"%{search}%"),
                Memory.content.ilike(f"%{search}%"),
            )
        )

    # Count
    count_query = select(func.count(Memory.id)).where(Memory.project_id == project_id)
    if search:
        count_query = count_query.where(
            or_(
                Memory.title.ilike(f"%{search}%"),
                Memory.content.ilike(f"%{search}%"),
            )
        )

    total = (await db.execute(refresh_select_statement(count_query))).scalar()

    # Pagination
    query = query.order_by(Memory.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(refresh_select_statement(query))
    memories = result.scalars().all()

    return MemoryListResponse(
        memories=[MemoryResponse.from_orm(m) for m in memories],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/memories/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a specific memory."""
    result = await db.execute(
        refresh_select_statement(select(Memory).where(Memory.id == memory_id))
    )
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail=_("Memory not found"))

    # Check access
    # Simplified: Check if user has access to project
    user_project_result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                UserProject.user_id == current_user.id,
                UserProject.project_id == memory.project_id,
            )
        )
    )
    if not user_project_result.scalar_one_or_none():
        # Check ownership
        project_result = await db.execute(
            refresh_select_statement(select(Project).where(Project.id == memory.project_id))
        )
        project = project_result.scalar_one_or_none()
        if not project or project.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail=_("Access denied"))

    return MemoryResponse.from_orm(memory)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
) -> JSONResponse | Response:
    """Delete a memory from all storage systems (DB, Graphiti)."""
    # 1. Get memory to check permissions and project_id
    result = await db.execute(
        refresh_select_statement(select(Memory).where(Memory.id == memory_id))
    )
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail=_("Memory not found"))

    # 2. Check permissions
    if memory.author_id != current_user.id:
        if not await _has_project_admin_access(cast(Memory, memory), current_user, db):
            raise HTTPException(status_code=403, detail=_("Permission denied"))

    # 3. Delete from Graphiti/Neo4j using GraphitiAdapter
    # This ensures proper cleanup of orphaned entities and edges
    graph_cleanup_failed = False
    try:
        if graph_service is None:
            raise HTTPException(status_code=503, detail=_("Graph service not available"))
        await graph_service.delete_episode_by_memory_id(memory_id)
        logger.info(f"Deleted graph state for memory {memory_id} with proper cleanup")
    except Exception as e:
        graph_cleanup_failed = True
        logger.error(
            f"Failed to delete memory {memory_id} from graph: {e}. "
            "Orphaned data may remain in Neo4j. Proceeding with database deletion.",
            exc_info=True,
        )

    # 4. Delete from SQL Database
    await db.delete(memory)
    await db.commit()

    # 5. Delete searchable chunks via the shared helper.
    chunk_cleanup_failed = False
    try:
        await _delete_memory_chunks_for_request(db, memory_id, memory.project_id)
        await db.commit()
    except Exception as e:
        chunk_cleanup_failed = True
        await db.rollback()
        logger.error(
            "Failed to delete memory chunks for %s: %s. Searchable chunks may remain stale.",
            memory_id,
            e,
            exc_info=True,
        )

    if graph_cleanup_failed or chunk_cleanup_failed:
        logger.warning(
            "Memory %s deleted from database with partial cleanup "
            "(graph_failed=%s, chunk_failed=%s)",
            memory_id,
            graph_cleanup_failed,
            chunk_cleanup_failed,
        )
        # Return 207 Multi-Status to indicate partial success
        return JSONResponse(
            status_code=207,
            content={
                "status": "partial_success",
                "message": _(
                    "Memory deleted from database, but one or more cleanup steps failed. Some graph or searchable chunk data may remain stale."
                ),
            },
        )

    return Response(status_code=204)


@router.post("/memories/{memory_id}/reprocess", response_model=MemoryResponse)
async def reprocess_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
) -> Any:
    """Manually trigger re-processing of a memory."""
    # 1. Get memory
    result = await db.execute(
        refresh_select_statement(select(Memory).where(Memory.id == memory_id))
    )
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail=_("Memory not found"))

    # Check if already processing to prevent duplicate tasks
    if memory.processing_status in ["PENDING", "PROCESSING"]:
        raise HTTPException(
            status_code=409,
            detail=_("Memory is already being processed. Please wait for completion."),
        )

    # 2. Check permissions
    if memory.author_id != current_user.id:
        if not await _has_memory_share_edit_permission(memory_id, current_user.id, db):
            # Check project owner
            user_project_result = await db.execute(
                refresh_select_statement(
                    select(UserProject).where(
                        UserProject.user_id == current_user.id,
                        UserProject.project_id == memory.project_id,
                        UserProject.role.in_(["owner", "admin"]),
                    )
                )
            )
            if not user_project_result.scalar_one_or_none():
                raise HTTPException(status_code=403, detail=_("Permission denied"))

    # 3. Clean up old episode data before reprocessing
    try:
        logger.info(f"Cleaning up old episode data for memory {memory_id} before reprocessing")
        if graph_service is not None:
            await graph_service.delete_episode_by_memory_id(memory_id)
    except Exception as e:
        logger.warning(f"Failed to clean up old episode data for memory {memory_id}: {e}")
        # Continue with reprocessing even if cleanup fails

    # 4. Trigger processing
    try:
        # Get project for tenant_id
        project_result = await db.execute(
            refresh_select_statement(select(Project).where(Project.id == memory.project_id))
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail=_("Project not found"))

        # Submit to Temporal workflow for processing
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.models import TaskLog

        task_id = str(uuid4())
        task_payload = {
            "group_id": memory.project_id,
            "name": memory.title or str(memory.id),
            "content": memory.content,
            "source_description": "User input (reprocess)",
            "episode_type": memory.content_type,
            "entity_types": None,
            "uuid": memory.id,
            "tenant_id": project.tenant_id,
            "project_id": memory.project_id,
            "user_id": str(current_user.id),
            "memory_id": memory.id,
        }

        # Create TaskLog record
        async with async_session_factory() as task_session, task_session.begin():
            task_log = TaskLog(
                id=task_id,
                group_id=memory.project_id,
                task_type="add_episode",
                status="PENDING",
                payload=task_payload,
                entity_type="episode",
                created_at=datetime.now(UTC),
            )
            task_session.add(task_log)

        task_payload["task_id"] = task_id

        # Start Temporal workflow
        workflow_id = f"episode-reprocess-{memory.id}"
        await workflow_engine.start_workflow(
            workflow_name="episode_processing",
            workflow_id=workflow_id,
            input_data=task_payload,
            task_queue="default",
        )

        memory.processing_status = "PENDING"
        memory.task_id = task_id
        await db.commit()
        await db.refresh(memory)

        logger.info(f"Memory {memory.id} re-queued for processing. Task: {task_id}")
        return MemoryResponse.from_orm(memory)

    except HTTPException as http_exc:
        # HTTPExceptions from validation (lines 528-540) occur before status update,
        # so no rollback needed. However, if any HTTPException occurs after status
        # update (line 556-557), we must rollback to avoid inconsistent state.
        # In the current implementation, no HTTPExceptions are raised after line 556,
        # but we include rollback here for safety in case the code evolves.
        await db.rollback()
        raise http_exc
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to reprocess memory {memory_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=_("Failed to queue memory for reprocessing. Please try again.")
        ) from e


async def _check_memory_edit_permission(memory: Any, current_user: User, db: AsyncSession) -> None:
    """Check if user has edit permission for the memory."""
    if memory.author_id == current_user.id:
        return
    # Check if user has edit permission through share
    if await _has_memory_share_edit_permission(memory.id, current_user.id, db):
        return
    # Check if user is project owner/admin
    user_project_result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                UserProject.user_id == current_user.id,
                UserProject.project_id == memory.project_id,
                UserProject.role.in_(["owner", "admin"]),
            )
        )
    )
    if not user_project_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail=_("Permission denied"))


async def _submit_reprocessing_workflow(
    memory: Any,
    current_user: User,
    db: AsyncSession,
    workflow_engine: WorkflowEnginePort,
    graph_service: GraphServicePort | None = None,
) -> None:
    """Submit memory for reprocessing via Temporal workflow."""
    try:
        if graph_service is not None:
            try:
                await graph_service.delete_episode_by_memory_id(memory.id)
                logger.info("Cleaned old graph state before updating memory %s", memory.id)
            except Exception as cleanup_error:
                logger.warning(
                    "Failed to clean old graph state before updating memory %s: %s",
                    memory.id,
                    cleanup_error,
                )

        # Get project for tenant_id
        project_result = await db.execute(
            refresh_select_statement(select(Project).where(Project.id == memory.project_id))
        )
        project = project_result.scalar_one_or_none()
        if not project:
            logger.error(f"Project {memory.project_id} not found for memory {memory.id}")
            memory.processing_status = "FAILED"
            return

        # Submit to Temporal workflow for processing
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.models import TaskLog

        task_id = str(uuid4())
        task_payload = {
            "group_id": memory.project_id,
            "name": memory.title or str(memory.id),
            "content": memory.content,
            "source_description": "User input (update)",
            "episode_type": memory.content_type,
            "entity_types": None,
            "uuid": memory.id,
            "tenant_id": project.tenant_id,
            "project_id": memory.project_id,
            "user_id": str(current_user.id),
            "memory_id": memory.id,
        }

        # Create TaskLog record
        async with async_session_factory() as task_session, task_session.begin():
            task_log = TaskLog(
                id=task_id,
                group_id=memory.project_id,
                task_type="add_episode",
                status="PENDING",
                payload=task_payload,
                entity_type="episode",
                created_at=datetime.now(UTC),
            )
            task_session.add(task_log)

        task_payload["task_id"] = task_id

        # Start Temporal workflow
        workflow_id = f"episode-update-{memory.id}-{task_id[:8]}"
        await workflow_engine.start_workflow(
            workflow_name="episode_processing",
            workflow_id=workflow_id,
            input_data=task_payload,
            task_queue="default",
        )
        memory.processing_status = "PENDING"
        memory.task_id = task_id
        logger.info(f"Memory {memory.id} content updated, triggered reprocessing task {task_id}")
    except Exception as e:
        memory.processing_status = "FAILED"
        memory.processing_error = f"Reprocessing failed: {e!s}"
        logger.error(
            f"Failed to trigger reprocessing for memory {memory.id}: {e}. "
            "Content was updated but knowledge graph won't reflect changes.",
            exc_info=True,
        )


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    memory_data: MemoryUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> Any:
    """Update an existing memory with optimistic locking."""
    # 1. Get memory
    result = await db.execute(
        refresh_select_statement(select(Memory).where(Memory.id == memory_id))
    )
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail=_("Memory not found"))

    # 2. Check permissions (owner or shared with edit permission)
    await _check_memory_edit_permission(memory, current_user, db)

    # 3. Optimistic locking: check version
    if memory.version != memory_data.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_(
                "Version conflict: Memory was modified by another user. Please refresh and try again."
            ),
        )

    original_content = memory.content
    original_meta = dict(memory.meta or {})

    # Check if content needs reprocessing
    should_reprocess = (memory_data.title is not None and memory_data.title != memory.title) or (
        memory_data.content is not None and memory_data.content != memory.content
    )

    # 4. Update fields
    if memory_data.title is not None:
        memory.title = memory_data.title
    if memory_data.content is not None:
        memory.content = memory_data.content
    if memory_data.tags is not None:
        memory.tags = memory_data.tags
    if memory_data.entities is not None:
        memory.entities = memory_data.entities
    if memory_data.relationships is not None:
        memory.relationships = memory_data.relationships
    if memory_data.metadata is not None:
        memory.meta = memory_data.metadata

    # 5. Increment version
    memory.version += 1

    # 6. Reprocess if needed
    if should_reprocess:
        await _submit_reprocessing_workflow(
            memory,
            current_user,
            db,
            workflow_engine,
            graph_service,
        )

    # 7. Save to database
    await db.commit()
    await db.refresh(memory)

    should_sync_chunks = (
        memory.content != original_content or dict(memory.meta or {}) != original_meta
    )
    if should_sync_chunks:
        task_session_factory = _build_request_session_factory(db)
        background_tasks.add_task(
            _background_index_memory,
            memory_id=memory.id,
            content=memory.content,
            project_id=memory.project_id,
            category=(memory.meta or {}).get("category", "other"),
            metadata=memory.meta,
            graph_service=graph_service,
            session_factory=task_session_factory,
        )

    logger.info(f"Updated memory {memory_id} to version {memory.version}")

    return MemoryResponse.from_orm(memory)
