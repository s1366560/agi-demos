"""Project management API endpoints."""

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectStats,
    ProjectUpdate,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graphiti_client,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Memory,
    Project,
    ToolExecutionRecord,
    User,
    UserProject,
    UserTenant,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
logger = logging.getLogger(__name__)


class AddProjectMemberRequest(BaseModel):
    user_id: str
    role: str | None = "member"


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Create a new project."""
    try:
        logger.info(
            f"Creating project '{project_data.name}' for user {current_user.id} in tenant {project_data.tenant_id}"
        )

        # Check if user has access to tenant
        user_tenant_result = await db.execute(
            select(UserTenant).where(
                and_(
                    UserTenant.user_id == current_user.id,
                    UserTenant.tenant_id == project_data.tenant_id,
                    UserTenant.role.in_(["owner", "admin"]),
                )
            )
        )
        if not user_tenant_result.scalar_one_or_none():
            logger.warning(
                f"User {current_user.id} denied permission to create project in tenant {project_data.tenant_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to create projects in this tenant",
            )

        # Create project
        project = Project(
            id=str(uuid4()),
            tenant_id=project_data.tenant_id,
            name=project_data.name,
            description=project_data.description,
            owner_id=current_user.id,
            memory_rules=project_data.memory_rules.model_dump(),
            graph_config=project_data.graph_config.model_dump(),
            is_public=project_data.is_public,
        )
        db.add(project)

        # Create user-project relationship
        user_project = UserProject(
            id=str(uuid4()),
            user_id=current_user.id,
            project_id=project.id,
            role="owner",
            permissions={"admin": True, "read": True, "write": True, "delete": True},
        )
        db.add(user_project)

        await db.commit()

        # Refresh project with relationships for Pydantic model
        result = await db.execute(
            select(Project).options(selectinload(Project.users)).where(Project.id == project.id)
        )
        project = result.scalar_one()

        return ProjectResponse.model_validate(project)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating project")
        raise HTTPException(status_code=500, detail=f"Internal Error: {e!s}") from e


@router.get("/", response_model=ProjectListResponse)
async def list_projects(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str | None = Query(None, description="Search query"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any=Depends(get_graphiti_client),
) -> ProjectListResponse:
    """List projects for the current user."""
    # Get project IDs user has access to
    user_projects_result = await db.execute(
        select(UserProject.project_id).where(UserProject.user_id == current_user.id)
    )
    project_ids = [row[0] for row in user_projects_result.fetchall()]

    if not project_ids:
        return ProjectListResponse(projects=[], total=0, page=page, page_size=page_size)

    # Build query
    query = select(Project).where(Project.id.in_(project_ids))

    if tenant_id:
        query = query.where(Project.tenant_id == tenant_id)

    if search:
        query = query.where(
            or_(
                Project.name.ilike(f"%{search}%"),
                Project.description.ilike(f"%{search}%"),
            )
        )

    # Get total count
    count_query = select(func.count(Project.id)).where(Project.id.in_(project_ids))
    if tenant_id:
        count_query = count_query.where(Project.tenant_id == tenant_id)
    if search:
        count_query = count_query.where(
            or_(
                Project.name.ilike(f"%{search}%"),
                Project.description.ilike(f"%{search}%"),
            )
        )
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Get paginated results
    query = (
        query.offset((page - 1) * page_size).limit(page_size).options(selectinload(Project.users))
    )
    result = await db.execute(query)
    projects = result.scalars().all()

    # Calculate stats for projects
    project_responses = []
    if projects:
        project_ids_in_page = [p.id for p in projects]

        # Memory stats
        memory_stats_result = await db.execute(
            select(
                Memory.project_id,
                func.count(Memory.id).label("count"),
                func.sum(func.length(Memory.content)).label("size"),
                func.max(Memory.created_at).label("last_created"),
            )
            .where(Memory.project_id.in_(project_ids_in_page))
            .group_by(Memory.project_id)
        )
        memory_stats = {
            row.project_id: {
                "count": row.count,
                "size": row.size or 0,
                "last_created": row.last_created,
            }
            for row in memory_stats_result.fetchall()
        }

        # Member stats
        member_stats_result = await db.execute(
            select(
                UserProject.project_id,
                func.count(UserProject.user_id).label("count"),
            )
            .where(UserProject.project_id.in_(project_ids_in_page))
            .group_by(UserProject.project_id)
        )
        member_stats = {row.project_id: row.count for row in member_stats_result.fetchall()}

        # Graph stats for active nodes
        node_stats = {}
        # TODO: Implement bulk stats fetch if possible, or skip for performance
        # For now we assume we might skip or do it individually if critical
        # The original code called graphiti_service.get_graph_stats(project_id)
        # We can use graphiti_client.driver.execute_query to get counts directly
        # But for now, let's keep it simple and default to 0 to avoid complex async loops
        # or implement simple query if easy.

        for project in projects:
            p_resp = ProjectResponse.model_validate(project)

            m_stats = memory_stats.get(project.id, {"count": 0, "size": 0, "last_created": None})
            member_count = member_stats.get(project.id, 0)

            # Calculate last active
            last_active = project.updated_at
            if m_stats["last_created"]:
                if not last_active or m_stats["last_created"] > last_active:
                    last_active = m_stats["last_created"]

            # Get node count from Graphiti
            node_count = node_stats.get(project.id, 0)

            p_resp.stats = ProjectStats(
                memory_count=m_stats["count"],
                storage_used=m_stats["size"],
                node_count=node_count,
                member_count=member_count,
                last_active=last_active,
            )
            project_responses.append(p_resp)

    return ProjectListResponse(
        projects=project_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Get project by ID."""
    # Use project_id directly as string (preserves original format from database)
    # Check if user has access to project
    user_project_result = await db.execute(
        select(UserProject).where(
            and_(UserProject.user_id == current_user.id, UserProject.project_id == project_id)
        )
    )
    if not user_project_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to project"
        )

    # Get project
    result = await db.execute(
        select(Project).options(selectinload(Project.users)).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return ProjectResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Update project."""
    # Check if user is owner or admin
    user_project_result = await db.execute(
        select(UserProject).where(
            and_(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
                UserProject.role.in_(["owner", "admin"]),
            )
        )
    )
    if not user_project_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owner or admin can update project",
        )

    # Get project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Update fields
    update_data = project_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "memory_rules":
            project.memory_rules = value
        elif field == "graph_config":
            project.graph_config = value
        elif field == "is_public":
            project.is_public = value
        else:
            setattr(project, field, value)

    await db.commit()

    # Refresh with relationships
    result = await db.execute(
        select(Project).options(selectinload(Project.users)).where(Project.id == project.id)
    )
    project = result.scalar_one()

    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete project."""
    # Use project_id directly
    # Check if user is owner
    user_project_result = await db.execute(
        select(UserProject).where(
            and_(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
                UserProject.role == "owner",
            )
        )
    )
    if not user_project_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only project owner can delete project"
        )

    # Get project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    await db.delete(project)
    await db.commit()


@router.post("/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_project_member(
    project_id: str,
    body: AddProjectMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add member to project."""
    # No explicit header 401 check; rely on role permission checks
    # Validate role
    role = body.role or "member"
    if role not in ["owner", "admin", "member", "viewer", "editor"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    # Check if current user is owner or admin
    user_project_result = await db.execute(
        select(UserProject).where(
            and_(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
                UserProject.role.in_(["owner", "admin"]),
            )
        )
    )
    if not user_project_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owner or admin can add members",
        )

    # Check if project exists
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Check if user exists
    user_result = await db.execute(select(User).where(User.id == body.user_id))
    if not user_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check if user is already member
    existing_result = await db.execute(
        select(UserProject).where(
            and_(UserProject.user_id == body.user_id, UserProject.project_id == project_id)
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this project",
        )

    user_project = UserProject(
        id=str(uuid4()),
        user_id=body.user_id,
        project_id=project_id,
        role=role,
        permissions={"read": True, "write": role in ["admin", "member", "editor"]},
    )
    db.add(user_project)
    await db.commit()

    return {"message": "Member added successfully", "user_id": body.user_id, "role": role}


@router.patch("/{project_id}/members/{user_id}", response_model=dict)
async def update_project_member(
    project_id: str,
    user_id: str,
    member_data: ProjectMemberUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update project member role."""
    # Use project_id directly
    role = member_data.role

    # Check if current user is owner or admin
    user_project_result = await db.execute(
        select(UserProject).where(
            and_(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
                UserProject.role.in_(["owner", "admin"]),
            )
        )
    )
    if not user_project_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owner or admin can update members",
        )

    # Check if user is a member
    result = await db.execute(
        select(UserProject).where(
            and_(UserProject.user_id == user_id, UserProject.project_id == project_id)
        )
    )
    user_project = result.scalar_one_or_none()
    if not user_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User is not a member of this project"
        )

    # Cannot update owner's role
    if user_project.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot update project owner role"
        )

    # Update role
    user_project.role = role
    # Update permissions based on role
    user_project.permissions = {"read": True, "write": role in ["admin", "member"]}

    await db.commit()

    return {"message": "Member role updated successfully", "user_id": user_id, "role": role}


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(
    project_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove member from project."""
    # Use project_id directly
    # Check if current user is owner or admin
    user_project_result = await db.execute(
        select(UserProject).where(
            and_(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
                UserProject.role.in_(["owner", "admin"]),
            )
        )
    )
    if not user_project_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only project owner can remove members"
        )

    # Cannot remove owner
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove project owner"
        )

    # Remove user-project relationship
    result = await db.execute(
        select(UserProject).where(
            and_(UserProject.user_id == user_id, UserProject.project_id == project_id)
        )
    )
    user_project = result.scalar_one_or_none()
    if not user_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User is not a member of this project"
        )

    await db.delete(user_project)
    await db.commit()


@router.get("/{project_id}/members")
async def list_project_members(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List project members."""
    # Use project_id directly
    # Existence check first
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if not project:
        # If obviously invalid uuid format, return 422 per contract expectations
        uuid_like = re.match(r"^[0-9a-f-]{36}$", project_id) is not None
        if not uuid_like:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid UUID"
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    # Check if user has access to project
    user_project_result = await db.execute(
        select(UserProject).where(
            and_(UserProject.user_id == current_user.id, UserProject.project_id == project_id)
        )
    )
    if not user_project_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to project"
        )

    # Get all members
    result = await db.execute(
        select(UserProject, User)
        .join(User, UserProject.user_id == User.id)
        .where(UserProject.project_id == project_id)
    )
    members = []
    for user_project, user in result.fetchall():
        members.append(
            {
                "user_id": user.id,
                "email": user.email,
                "name": user.full_name,  # Fixed: use full_name instead of name
                "role": user_project.role,
                "permissions": user_project.permissions,
                "created_at": user_project.created_at,
            }
        )

    return {"members": members, "total": len(members)}


@router.get("/{project_id}/stats", response_model=ProjectStats)
async def get_project_stats(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any=Depends(get_graphiti_client),
) -> ProjectStats:
    """Get project statistics for the dashboard."""
    # Use project_id directly
    try:
        # Check if user has access to project
        user_project_result = await db.execute(
            select(UserProject).where(
                and_(UserProject.user_id == current_user.id, UserProject.project_id == project_id)
            )
        )
        if not user_project_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to project"
            )

        # Get project
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Get memory stats
        memory_stats_result = await db.execute(
            select(
                func.count(Memory.id).label("count"),
                func.sum(func.length(Memory.content)).label("size"),
            ).where(Memory.project_id == project_id)
        )
        memory_stats = memory_stats_result.one()
        memory_count = memory_stats.count
        storage_used = memory_stats.size or 0

        # Get member count
        member_count_result = await db.execute(
            select(func.count(UserProject.id)).where(UserProject.project_id == project_id)
        )
        member_count = member_count_result.scalar()

        # Get active nodes (from Graphiti)
        # Active nodes are those with last_active timestamp within last 7 days
        from datetime import datetime, timedelta

        active_nodes = 0
        try:
            # Calculate threshold date (7 days ago)
            threshold_date = (datetime.now(UTC) - timedelta(days=7)).isoformat()

            # Query Graphiti for active nodes in this project
            query = """
                MATCH (n:Node)
                WHERE n.project_id = $project_id
                AND n.valid_at >= $threshold
                RETURN count(n) as active_count
            """

            result = await graphiti_client.driver.execute_query(
                query, project_id=project_id, threshold=threshold_date
            )

            # Extract count from result
            if hasattr(result, "records") and result.records:
                for record in result.records:
                    active_nodes = record.get("active_count", 0)
                    break
            elif result and len(result) > 0:
                # Fallback for old driver behavior or different result shape
                for record in result:
                    if hasattr(record, "get"):
                        active_nodes = record.get("active_count", 0)
                    break

            logger.info(f"Found {active_nodes} active nodes for project {project_id}")
        except Exception as e:
            logger.error(f"Failed to get active nodes from Graphiti: {e}")
            # Keep active_nodes as 0 on error

        # Get tenant limit for storage
        # tenant_result = await db.execute(select(Tenant).where(Tenant.id == project.tenant_id))
        # tenant = tenant_result.scalar_one_or_none()
        storage_limit = 1024 * 1024 * 1024  # Default 1GB
        # storage_limit = tenant.max_storage if tenant else 1024 * 1024 * 1024  # Default 1GB

        # Recent activity (from Memories)
        recent_memories_result = await db.execute(
            select(Memory, User)
            .join(User, Memory.author_id == User.id)
            .where(Memory.project_id == project_id)
            .order_by(Memory.created_at.desc())
            .limit(5)
        )
        activities = []
        for memory, user in recent_memories_result.fetchall():
            # Calculate relative time string
            from datetime import datetime

            now = datetime.now(UTC)
            diff = now - memory.created_at
            if diff.days > 0:
                time_str = f"{diff.days}d ago"
            elif diff.seconds >= 3600:
                time_str = f"{diff.seconds // 3600}h ago"
            elif diff.seconds >= 60:
                time_str = f"{diff.seconds // 60}m ago"
            else:
                time_str = "Just now"

            activities.append(
                {
                    "id": memory.id,
                    "user": user.full_name or user.email,
                    "action": "created a memory",
                    "target": memory.title or "Untitled Memory",
                    "time": time_str,
                }
            )

        # Get conversation count
        conversation_count_result = await db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.project_id == project_id)
        )
        conversation_count = conversation_count_result.scalar() or 0

        return ProjectStats(
            memory_count=memory_count,
            conversation_count=conversation_count,
            storage_used=storage_used,
            storage_limit=storage_limit,
            member_count=member_count,
            node_count=active_nodes,
            active_nodes=active_nodes,  # Add active_nodes field for frontend
            collaborators=member_count,
            recent_activity=activities,
            last_active=datetime.now(UTC),  # Add logic for last_active if needed
            system_status={
                "status": "operational",
                "indexing_active": True,
                "indexing_progress": 100,
            },
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Error getting project stats for {project_id}")
        raise HTTPException(
            status_code=500, detail="An error occurred while retrieving project statistics"
        ) from None


class TrendingEntity(BaseModel):
    """A trending entity in the project's knowledge graph."""

    name: str
    entity_type: str
    mention_count: int
    summary: str | None = None


class TrendingResponse(BaseModel):
    """Response for trending entities."""

    entities: list[TrendingEntity]


@router.get("/{project_id}/trending", response_model=TrendingResponse)
async def get_trending_entities(
    project_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any=Depends(get_graphiti_client),
) -> TrendingResponse:
    """Get trending entities in a project's knowledge graph."""
    try:
        # Verify project access
        access = await db.execute(
            select(UserProject).where(
                and_(
                    UserProject.user_id == current_user.id,
                    UserProject.project_id == project_id,
                )
            )
        )
        if not access.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Access denied")

        entities: list[TrendingEntity] = []
        try:
            query = """
                MATCH (n:Entity)
                WHERE n.project_id = $project_id
                OPTIONAL MATCH (n)-[r]-()
                WITH n, count(r) as rel_count
                ORDER BY rel_count DESC
                LIMIT $limit
                RETURN n.name as name,
                       coalesce(n.entity_type, 'unknown') as entity_type,
                       rel_count as mention_count,
                       n.summary as summary
            """
            result = await graphiti_client.driver.execute_query(
                query, project_id=project_id, limit=limit
            )
            if hasattr(result, "records"):
                for record in result.records:
                    entities.append(
                        TrendingEntity(
                            name=record.get("name", ""),
                            entity_type=record.get("entity_type", "unknown"),
                            mention_count=record.get("mention_count", 0),
                            summary=record.get("summary"),
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to query trending entities: {e}")

        return TrendingResponse(entities=entities)
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Error getting trending entities for {project_id}")
        raise HTTPException(status_code=500, detail="Failed to get trending entities") from None


class RecentSkillItem(BaseModel):
    """A recently used skill/tool."""

    name: str
    last_used: datetime
    usage_count: int


class RecentSkillsResponse(BaseModel):
    """Response for recently used skills."""

    skills: list[RecentSkillItem]


@router.get("/{project_id}/recent-skills", response_model=RecentSkillsResponse)
async def get_recent_skills(
    project_id: str,
    limit: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecentSkillsResponse:
    """Get recently used skills/tools in a project."""
    try:
        # Verify project access
        access = await db.execute(
            select(UserProject).where(
                and_(
                    UserProject.user_id == current_user.id,
                    UserProject.project_id == project_id,
                )
            )
        )
        if not access.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Access denied")

        skills: list[RecentSkillItem] = []
        try:
            result = await db.execute(
                select(
                    ToolExecutionRecord.tool_name,
                    func.max(ToolExecutionRecord.started_at).label("last_used"),
                    func.count(ToolExecutionRecord.id).label("usage_count"),
                )
                .join(
                    Conversation,
                    ToolExecutionRecord.conversation_id == Conversation.id,
                )
                .where(Conversation.project_id == project_id)
                .group_by(ToolExecutionRecord.tool_name)
                .order_by(func.max(ToolExecutionRecord.started_at).desc())
                .limit(limit)
            )
            for row in result.fetchall():
                skills.append(
                    RecentSkillItem(
                        name=row.tool_name,
                        last_used=row.last_used,
                        usage_count=row.usage_count,
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to query recent skills: {e}")

        return RecentSkillsResponse(skills=skills)
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Error getting recent skills for {project_id}")
        raise HTTPException(status_code=500, detail="Failed to get recent skills") from None
