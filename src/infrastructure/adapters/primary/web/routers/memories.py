"""Memories API endpoints."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graph_service,
    get_graphiti_client,
    get_workflow_engine,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
    UserProject,
)

logger = logging.getLogger(__name__)


async def _background_index_memory(
    memory_id: str,
    content: str,
    project_id: str,
    category: str = "other",
) -> None:
    """Index a memory's content as chunks in the background."""
    try:
        from src.application.services.memory_index_service import MemoryIndexService
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
            SqlChunkRepository,
        )

        async with async_session_factory() as session:
            chunk_repo = SqlChunkRepository(session)
            # Use basic embedding (no Redis cache in background task for simplicity)
            from src.infrastructure.llm.embedding_service import EmbeddingService

            embedding_service = EmbeddingService()
            index_service = MemoryIndexService(chunk_repo, embedding_service)
            count = await index_service.index_memory(memory_id, content, project_id, category)
            await session.commit()
            logger.info(f"Background indexed memory {memory_id}: {count} chunks")
    except Exception as e:
        logger.warning(f"Background memory indexing failed for {memory_id}: {e}")


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
    metadata: dict = {}


class MemoryResponse(BaseModel):
    id: str
    project_id: str
    title: str
    content: str
    content_type: str
    tags: list[str]
    entities: list[dict]
    relationships: list[dict]
    version: int
    author_id: str
    collaborators: list[str]
    is_public: bool
    status: str
    processing_status: str
    meta: dict = Field(serialization_alias="metadata")
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
    entities: list[dict] | None = None
    relationships: list[dict] | None = None
    metadata: dict | None = None
    version: int  # Required for optimistic locking


class MemoryShareCreate(BaseModel):
    """Schema for creating a memory share."""

    target_type: str  # 'user' or 'project'
    target_id: str  # User ID or Project ID
    permission_level: str  # 'view' or 'edit'
    expires_at: datetime | None = None


class MemoryShareResponse(BaseModel):
    """Schema for memory share response."""

    id: str
    memory_id: str
    shared_with_user_id: str | None
    shared_with_project_id: str | None
    permissions: dict
    shared_by: str
    created_at: datetime
    expires_at: datetime | None
    access_count: int = 0

    class Config:
        from_attributes = True


# --- Endpoints ---
@router.post("/memories/extract-entities")
async def extract_entities(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = payload.get("content")
    memory_id = payload.get("memory_id")
    if not content and memory_id:
        result = await db.execute(select(Memory).where(Memory.id == memory_id))
        mem = result.scalar_one_or_none()
        if not mem:
            raise HTTPException(status_code=404, detail="Memory not found")
        content = mem.content
    content = content or ""
    tokens = [t for t in content.split() if t[:1].isupper()]
    entities = [{"name": t.strip(",.()"), "type": "Entity", "confidence": 0.5} for t in tokens[:10]]
    return {"entities": entities, "source": "rule_based"}


@router.post("/memories/extract-relationships")
async def extract_relationships(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = payload.get("content")
    memory_id = payload.get("memory_id")
    if not content and memory_id:
        result = await db.execute(select(Memory).where(Memory.id == memory_id))
        mem = result.scalar_one_or_none()
        if not mem:
            raise HTTPException(status_code=404, detail="Memory not found")
        content = mem.content
    content = content or ""
    words = [w.strip(",.()") for w in content.split() if w]
    relationships = []
    for i in range(0, min(len(words), 6), 3):
        if i + 2 < len(words):
            relationships.append(
                {
                    "source": words[i],
                    "target": words[i + 1],
                    "type": "related_to",
                    "confidence": 0.4,
                }
            )
    return {"relationships": relationships, "source": "rule_based"}


@router.post("/memories/", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    memory_data: MemoryCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any=Depends(get_graphiti_client),
    workflow_engine: Any=Depends(get_workflow_engine),
):
    """Create a new memory.

    This endpoint stores memory using a hybrid approach:
    1. Immediate storage in DB
    2. Asynchronous graph building via Graphiti for relationship extraction
    """
    try:
        project_id = memory_data.project_id
        # Verify project access
        result = await db.execute(
            select(UserProject).where(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
            )
        )
        user_project = result.scalar_one_or_none()

        project = None
        if not user_project:
            # Check if project is public or user is owner
            project_result = await db.execute(select(Project).where(Project.id == project_id))
            project = project_result.scalar_one_or_none()
            if not project or project.owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to this project",
                )
        else:
            if user_project.role == "viewer":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Viewers cannot create memories",
                )
            if not project:
                project_result = await db.execute(select(Project).where(Project.id == project_id))
                project = project_result.scalar_one()

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
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
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
            async with async_session_factory() as task_session, task_session.begin():
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
            memory.processing_error = f"Failed to queue for processing: {e!s}"

        await db.commit()
        await db.refresh(memory)

        # Auto-index memory content as chunks (non-blocking)
        background_tasks.add_task(
            _background_index_memory,
            memory_id=memory.id,
            content=memory_data.content,
            project_id=project_id,
        )

        return MemoryResponse.from_orm(memory)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating memory: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/memories/", response_model=MemoryListResponse)
async def list_memories(
    project_id: str = Query(..., description="Project ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str | None = Query(None, description="Search query"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List memories for a project."""
    # Verify access
    user_project_result = await db.execute(
        select(UserProject).where(
            UserProject.user_id == current_user.id,
            UserProject.project_id == project_id,
        )
    )
    if not user_project_result.scalar_one_or_none():
        # Check ownership
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if not project or project.owner_id != current_user.id:
            # TODO: Check if project is public?
            raise HTTPException(status_code=403, detail="Access denied")

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

    total = (await db.execute(count_query)).scalar()

    # Pagination
    query = query.order_by(Memory.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
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
):
    """Get a specific memory."""
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Check access
    # Simplified: Check if user has access to project
    user_project_result = await db.execute(
        select(UserProject).where(
            UserProject.user_id == current_user.id,
            UserProject.project_id == memory.project_id,
        )
    )
    if not user_project_result.scalar_one_or_none():
        # Check ownership
        project_result = await db.execute(select(Project).where(Project.id == memory.project_id))
        project = project_result.scalar_one_or_none()
        if not project or project.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

    return MemoryResponse.from_orm(memory)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_service: Any=Depends(get_graph_service),
):
    """Delete a memory from all storage systems (DB, Graphiti)."""
    # 1. Get memory to check permissions and project_id
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    # 2. Check permissions
    if memory.author_id != current_user.id:
        # Check if user is project owner/admin
        user_project_result = await db.execute(
            select(UserProject).where(
                UserProject.user_id == current_user.id,
                UserProject.project_id == memory.project_id,
                UserProject.role.in_(["owner", "admin"]),
            )
        )
        if not user_project_result.scalar_one_or_none():
            # Check if user is tenant owner? (Optional, skipping for now)
            raise HTTPException(status_code=403, detail="Permission denied")

    # 3. Delete from Graphiti/Neo4j using GraphitiAdapter
    # This ensures proper cleanup of orphaned entities and edges
    graph_cleanup_failed = False
    try:
        await graph_service.remove_episode(memory_id)
        logger.info(f"Deleted episode {memory_id} from graph with proper cleanup")
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

    if graph_cleanup_failed:
        logger.warning(f"Memory {memory_id} deleted from database but graph cleanup failed")
        # Return 207 Multi-Status to indicate partial success
        return JSONResponse(
            status_code=207,
            content={
                "status": "partial_success",
                "message": "Memory deleted from database but graph cleanup failed. Some orphaned data may remain in Neo4j.",
            },
        )

    return Response(status_code=204)


@router.post("/memories/{memory_id}/reprocess", response_model=MemoryResponse)
async def reprocess_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workflow_engine: Any=Depends(get_workflow_engine),
    graph_service: Any=Depends(get_graph_service),
):
    """Manually trigger re-processing of a memory."""
    # 1. Get memory
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Check if already processing to prevent duplicate tasks
    if memory.processing_status in ["PENDING", "PROCESSING"]:
        raise HTTPException(
            status_code=409,
            detail="Memory is already being processed. Please wait for completion.",
        )

    # 2. Check permissions
    if memory.author_id != current_user.id:
        # Check shared edit permission
        share_result = await db.execute(
            select(MemoryShare).where(
                MemoryShare.memory_id == memory_id,
                MemoryShare.shared_with_user_id == current_user.id,
                MemoryShare.permission_level == "edit",
            )
        )
        if not share_result.scalar_one_or_none():
            # Check project owner
            user_project_result = await db.execute(
                select(UserProject).where(
                    UserProject.user_id == current_user.id,
                    UserProject.project_id == memory.project_id,
                    UserProject.role.in_(["owner", "admin"]),
                )
            )
            if not user_project_result.scalar_one_or_none():
                raise HTTPException(status_code=403, detail="Permission denied")

    # 3. Clean up old episode data before reprocessing
    try:
        logger.info(f"Cleaning up old episode data for memory {memory_id} before reprocessing")
        await graph_service.remove_episode_by_memory_id(memory_id)
    except Exception as e:
        logger.warning(f"Failed to clean up old episode data for memory {memory_id}: {e}")
        # Continue with reprocessing even if cleanup fails

    # 4. Trigger processing
    try:
        # Get project for tenant_id
        project_result = await db.execute(select(Project).where(Project.id == memory.project_id))
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

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
            status_code=500, detail="Failed to queue memory for reprocessing. Please try again."
        ) from e


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    memory_data: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workflow_engine: Any=Depends(get_workflow_engine),
):
    """Update an existing memory with optimistic locking."""
    # 1. Get memory
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    # 2. Check permissions (owner or shared with edit permission)
    if memory.author_id != current_user.id:
        # Check if user has edit permission through share
        share_result = await db.execute(
            select(MemoryShare).where(
                MemoryShare.memory_id == memory_id,
                MemoryShare.shared_with_user_id == current_user.id,
                MemoryShare.permission_level == "edit",
            )
        )
        has_edit_share = share_result.scalar_one_or_none()

        if not has_edit_share:
            # Check if user is project owner/admin
            user_project_result = await db.execute(
                select(UserProject).where(
                    UserProject.user_id == current_user.id,
                    UserProject.project_id == memory.project_id,
                    UserProject.role.in_(["owner", "admin"]),
                )
            )
            if not user_project_result.scalar_one_or_none():
                raise HTTPException(status_code=403, detail="Permission denied")

    # 3. Optimistic locking: check version
    if memory.version != memory_data.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Version conflict: Memory was modified by another user. Please refresh and try again.",
        )

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
        try:
            # Get project for tenant_id
            project_result = await db.execute(
                select(Project).where(Project.id == memory.project_id)
            )
            project = project_result.scalar_one_or_none()
            if not project:
                logger.error(f"Project {memory.project_id} not found for memory {memory.id}")
                memory.processing_status = "FAILED"
            else:
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
                async with async_session_factory() as task_session:
                    async with task_session.begin():
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
                logger.info(
                    f"Memory {memory.id} content updated, triggered reprocessing task {task_id}"
                )
        except Exception as e:
            # Content update will succeed, but graph reprocessing failed.
            # Set status to FAILED to indicate the knowledge graph is out of sync.
            # Note: We intentionally catch all exceptions here because we want the
            # content update to succeed even if reprocessing fails. This is better
            # than rolling back the content changes.
            memory.processing_status = "FAILED"
            memory.processing_error = f"Reprocessing failed: {e!s}"
            logger.error(
                f"Failed to trigger reprocessing for memory {memory.id}: {e}. "
                "Content was updated but knowledge graph won't reflect changes.",
                exc_info=True,
            )

    # 7. Save to database
    await db.commit()
    await db.refresh(memory)

    logger.info(f"Updated memory {memory_id} to version {memory.version}")

    return MemoryResponse.from_orm(memory)


@router.post("/memories/{memory_id}/shares", status_code=status.HTTP_201_CREATED)
async def create_memory_share(
    memory_id: str,
    share_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Share a memory - accepts both strict and lenient payloads."""
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    if memory.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    # Strict payload support
    target_type = share_data.get("target_type")
    permission_level = share_data.get("permission_level")
    target_id = share_data.get("target_id")
    if target_type:
        if target_type not in ["user", "project"]:
            raise HTTPException(status_code=400, detail="target_type must be 'user' or 'project'")
        if permission_level not in ["view", "edit"]:
            raise HTTPException(status_code=400, detail="permission_level must be 'view' or 'edit'")
        # Duplicate check
        if target_type == "user":
            existing_share = await db.execute(
                select(MemoryShare).where(
                    MemoryShare.memory_id == memory_id, MemoryShare.shared_with_user_id == target_id
                )
            )
        else:
            existing_share = await db.execute(
                select(MemoryShare).where(
                    MemoryShare.memory_id == memory_id,
                    MemoryShare.shared_with_project_id == target_id,
                )
            )
        if existing_share.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Memory already shared with this target")

    # Parse expires_at - throw error on invalid format instead of silent fallback
    expires_at = None
    if share_data.get("expires_at"):
        try:
            expires_at = datetime.fromisoformat(share_data["expires_at"])
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid expires_at format: {share_data['expires_at']}. Use ISO 8601 format (e.g., 2024-12-31T23:59:59).",
            ) from None
    elif "expires_in_days" in share_data:
        days = share_data["expires_in_days"]
        if isinstance(days, int) and days > 0:
            expires_at = datetime.now(UTC) + timedelta(days=days)
    share = MemoryShare(
        id=str(uuid4()),
        memory_id=memory_id,
        shared_with_user_id=target_id if target_type == "user" else None,
        shared_with_project_id=target_id if target_type == "project" else None,
        permissions=share_data.get(
            "permissions", {"view": True, "edit": permission_level == "edit"}
        )
        if permission_level
        else share_data.get("permissions", {"view": True, "edit": False}),
        shared_by=current_user.id,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
        access_count=0,
    )
    db.add(share)
    await db.commit()
    return {
        "id": share.id,
        "share_token": share.id,
        "memory_id": memory_id,
        "shared_with_user_id": share.shared_with_user_id,
        "shared_with_project_id": share.shared_with_project_id,
        "permissions": share.permissions,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "created_at": share.created_at.isoformat(),
        "access_count": share.access_count,
    }


@router.delete("/memories/{memory_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_share(
    memory_id: str,
    share_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a memory share."""
    # 1. Get memory and verify ownership
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Only owner can delete shares
    if memory.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # 2. Get share
    result = await db.execute(select(MemoryShare).where(MemoryShare.id == share_id))
    share = result.scalar_one_or_none()

    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    # 3. Verify share belongs to this memory
    if share.memory_id != memory_id:
        raise HTTPException(status_code=400, detail="Share does not belong to this memory")

    # 4. Delete share
    await db.delete(share)
    await db.commit()

    logger.info(f"Deleted share {share_id} for memory {memory_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
