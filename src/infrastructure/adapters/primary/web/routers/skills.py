"""
Skill Management API endpoints.

Provides REST API for managing skills in the Agent Skill System (L2 layer).
Skills encapsulate domain knowledge and tool compositions for specific task patterns.

Three-level scoping for multi-tenant isolation:
- system: Built-in skills shared by all tenants (can be disabled/overridden)
- tenant: Tenant-level skills shared within a tenant
- project: Project-specific skills (highest priority)
"""

import logging
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus, TriggerPattern, TriggerType
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.
    """
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/skills", tags=["Skills"])


# === Pydantic Models ===


class TriggerPatternCreate(BaseModel):
    """Schema for creating a trigger pattern."""

    pattern: str = Field(..., description="The trigger pattern")
    weight: float = Field(1.0, ge=0.0, le=1.0, description="Pattern weight (0-1)")
    examples: list[str] = Field(default_factory=list, description="Example queries")


class SkillCreate(BaseModel):
    """Schema for creating a new skill."""

    name: str = Field(..., min_length=1, max_length=200, description="Skill name")
    description: str = Field(..., min_length=1, description="Skill description")
    trigger_type: str = Field("keyword", description="Trigger type: keyword, semantic, hybrid")
    trigger_patterns: list[TriggerPatternCreate] = Field(
        default_factory=list, description="Trigger patterns"
    )
    tools: list[str] = Field(..., min_items=1, description="List of tool names")
    prompt_template: str | None = Field(None, description="Optional prompt template")
    full_content: str | None = Field(None, description="Full SKILL.md content")
    project_id: str | None = Field(
        None, description="Optional project ID (required for PROJECT scope)"
    )
    scope: str = Field(
        "tenant", description="Skill scope: tenant or project (cannot create system)"
    )
    metadata: dict[str, Any] | None = Field(None, description="Optional metadata")


class SkillUpdate(BaseModel):
    """Schema for updating a skill."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, min_length=1)
    trigger_type: str | None = Field(None)
    trigger_patterns: list[TriggerPatternCreate] | None = Field(None)
    tools: list[str] | None = Field(None, min_items=1)
    prompt_template: str | None = Field(None)
    full_content: str | None = Field(None, description="Full SKILL.md content")
    status: str | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)


class SkillResponse(BaseModel):
    """Schema for skill response."""

    id: str
    tenant_id: str
    project_id: str | None
    name: str
    description: str
    trigger_type: str
    trigger_patterns: list[dict[str, Any]]
    tools: list[str]
    prompt_template: str | None
    full_content: str | None = None
    status: str
    scope: str
    is_system_skill: bool = False
    success_rate: float
    success_count: int
    failure_count: int
    usage_count: int
    created_at: str
    updated_at: str
    metadata: dict[str, Any] | None
    current_version: int = 0
    version_label: str | None = None


class SkillMatchRequest(BaseModel):
    """Schema for skill matching request."""

    query: str = Field(..., min_length=1, description="Query to match against skills")
    threshold: float = Field(0.5, ge=0.0, le=1.0, description="Match threshold")
    limit: int = Field(5, ge=1, le=20, description="Maximum results")


class SkillListResponse(BaseModel):
    """Schema for skill list response."""

    skills: list[SkillResponse]
    total: int


# === Helper Functions ===


def skill_to_response(skill: Skill) -> SkillResponse:
    """Convert domain Skill to response model."""
    return SkillResponse(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        trigger_type=skill.trigger_type.value,
        trigger_patterns=[p.to_dict() for p in skill.trigger_patterns],
        tools=list(skill.tools),
        prompt_template=skill.prompt_template,
        full_content=skill.full_content,
        status=skill.status.value,
        scope=skill.scope.value,
        is_system_skill=skill.is_system_skill,
        success_rate=skill.success_rate,
        success_count=skill.success_count,
        failure_count=skill.failure_count,
        usage_count=skill.usage_count,
        created_at=skill.created_at.isoformat(),
        updated_at=skill.updated_at.isoformat(),
        metadata=skill.metadata,
        current_version=getattr(skill, "current_version", 0),
        version_label=getattr(skill, "version_label", None),
    )


# === API Endpoints ===


@router.post("/", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: Request,
    data: SkillCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> skill_to_response:
    """
    Create a new skill.

    Skills can be created at tenant or project level. System-level skills
    cannot be created via API (they are loaded from the builtin directory).
    """
    try:
        # Validate scope
        try:
            scope = SkillScope(data.scope)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid scope: {data.scope}. Must be 'tenant' or 'project'",
            ) from None

        if scope == SkillScope.SYSTEM:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create system-level skills via API",
            )

        if scope == SkillScope.PROJECT and not data.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="project_id is required for project-scoped skills",
            )

        container = get_container_with_db(request, db)

        # Convert trigger patterns
        trigger_patterns = [
            TriggerPattern(
                pattern=p.pattern,
                weight=p.weight,
                examples=p.examples,
            )
            for p in data.trigger_patterns
        ]

        # Create skill
        skill = Skill.create(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            tools=data.tools,
            trigger_type=TriggerType(data.trigger_type),
            trigger_patterns=trigger_patterns,
            project_id=data.project_id,
            prompt_template=data.prompt_template,
            full_content=data.full_content,
            metadata=data.metadata,
            scope=scope,
            is_system_skill=False,
        )

        repo = container.skill_repository()
        created_skill = await repo.create(skill)
        await db.commit()

        logger.info(f"Skill created: {created_skill.id} (scope: {scope.value})")
        return skill_to_response(created_skill)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/", response_model=SkillListResponse)
async def list_skills(
    request: Request,
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    scope_filter: str | None = Query(
        None, alias="scope", description="Filter by scope: system, tenant, project"
    ),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillListResponse:
    """
    List all skills for the current tenant.

    Merges skills from both filesystem (SKILL.md) and database sources.
    Optionally filter by scope (system, tenant, project) and status.
    """
    from pathlib import Path

    from src.application.services.skill_service import SkillService

    container = get_container_with_db(request, db)
    skill_repo = container.skill_repository()

    skill_status = SkillStatus(status_filter) if status_filter else None
    skill_scope = SkillScope(scope_filter) if scope_filter else None

    skill_service = SkillService.create(
        skill_repository=skill_repo,
        base_path=Path.cwd(),
        tenant_id=tenant_id,
        include_system=True,
    )

    skills = await skill_service.list_available_skills(
        tenant_id=tenant_id,
        tier=2,
        status=skill_status,
        scope=skill_scope,
    )

    # Apply pagination
    total = len(skills)
    skills = skills[offset : offset + limit]

    return SkillListResponse(
        skills=[skill_to_response(s) for s in skills],
        total=total,
    )


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> skill_to_response:
    """
    Get a specific skill by ID.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    return skill_to_response(skill)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    request: Request,
    skill_id: str,
    data: SkillUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> skill_to_response:
    """
    Update an existing skill.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # Update fields
    from datetime import datetime

    trigger_patterns = skill.trigger_patterns
    if data.trigger_patterns is not None:
        trigger_patterns = [
            TriggerPattern(pattern=p.pattern, weight=p.weight, examples=p.examples)
            for p in data.trigger_patterns
        ]

    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,  # project_id cannot be changed
        name=data.name if data.name else skill.name,
        description=data.description if data.description else skill.description,
        trigger_type=TriggerType(data.trigger_type) if data.trigger_type else skill.trigger_type,
        trigger_patterns=trigger_patterns,
        tools=data.tools if data.tools else skill.tools,
        prompt_template=data.prompt_template
        if data.prompt_template is not None
        else skill.prompt_template,
        status=SkillStatus(data.status) if data.status else skill.status,
        success_count=skill.success_count,
        failure_count=skill.failure_count,
        created_at=skill.created_at,
        updated_at=datetime.now(UTC),
        metadata=data.metadata if data.metadata is not None else skill.metadata,
    )

    result = await repo.update(updated_skill)
    await db.commit()

    logger.info(f"Skill updated: {skill_id}")
    return skill_to_response(result)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a skill.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    await repo.delete(skill_id)
    await db.commit()

    logger.info(f"Skill deleted: {skill_id}")


@router.post("/match", response_model=list[SkillResponse])
async def match_skills(
    request: Request,
    data: SkillMatchRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[Any]:
    """
    Find skills that match a query.

    Uses trigger patterns to find matching skills.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skills = await repo.find_matching_skills(
        tenant_id=tenant_id,
        query=data.query,
        threshold=data.threshold,
        limit=data.limit,
    )

    return [skill_to_response(s) for s in skills]


@router.patch("/{skill_id}/status")
async def update_skill_status(
    request: Request,
    skill_id: str,
    status_value: str = Query(..., alias="status", description="New status"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> skill_to_response:
    """
    Update skill status (active, disabled, deprecated).
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    try:
        new_status = SkillStatus(status_value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {status_value}. Must be one of: active, disabled, deprecated",
        ) from None

    from datetime import datetime

    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        trigger_type=skill.trigger_type,
        trigger_patterns=skill.trigger_patterns,
        tools=skill.tools,
        prompt_template=skill.prompt_template,
        full_content=skill.full_content,
        status=new_status,
        success_count=skill.success_count,
        failure_count=skill.failure_count,
        created_at=skill.created_at,
        updated_at=datetime.now(UTC),
        metadata=skill.metadata,
        scope=skill.scope,
        is_system_skill=skill.is_system_skill,
    )

    result = await repo.update(updated_skill)
    await db.commit()

    logger.info(f"Skill status updated: {skill_id} -> {status_value}")
    return skill_to_response(result)


@router.get("/{skill_id}/stats")
async def get_skill_stats(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get usage statistics for a skill.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    return {
        "skill_id": skill.id,
        "name": skill.name,
        "success_count": skill.success_count,
        "failure_count": skill.failure_count,
        "usage_count": skill.usage_count,
        "success_rate": skill.success_rate,
    }


# === System Skills Endpoints ===


@router.get("/system/list", response_model=SkillListResponse)
async def list_system_skills(
    request: Request,
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillListResponse:
    """
    List all system-level skills.

    System skills are built-in skills loaded from the filesystem.
    They can be disabled or overridden per tenant.
    """
    from pathlib import Path

    from src.application.services.skill_service import SkillService

    container = get_container_with_db(request, db)
    skill_repo = container.skill_repository()

    # Get the SkillService to load system skills from filesystem
    skill_service = SkillService.create(
        skill_repository=skill_repo,
        base_path=Path.cwd(),
        tenant_id=tenant_id,
        include_system=True,
    )

    skill_status = SkillStatus(status_filter) if status_filter else None
    skills = await skill_service.list_system_skills(tenant_id=tenant_id, tier=2)

    # Apply status filter if provided
    if skill_status:
        skills = [s for s in skills if s.status == skill_status]

    return SkillListResponse(
        skills=[skill_to_response(s) for s in skills],
        total=len(skills),
    )


# === Content Endpoints ===


class SkillContentResponse(BaseModel):
    """Schema for skill content response."""

    skill_id: str
    name: str
    full_content: str | None
    scope: str
    is_system_skill: bool


class SkillContentUpdate(BaseModel):
    """Schema for updating skill content."""

    full_content: str = Field(..., min_length=1, description="Full SKILL.md content")


@router.get("/{skill_id}/content", response_model=SkillContentResponse)
async def get_skill_content(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillContentResponse:
    """
    Get the full content of a skill.

    Returns the complete SKILL.md content for editing.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # Verify tenant access (system skills are accessible to all tenants)
    if not skill.is_system_skill and skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    return SkillContentResponse(
        skill_id=skill.id,
        name=skill.name,
        full_content=skill.full_content or skill.prompt_template,
        scope=skill.scope.value,
        is_system_skill=skill.is_system_skill,
    )


@router.put("/{skill_id}/content", response_model=SkillResponse)
async def update_skill_content(
    request: Request,
    skill_id: str,
    data: SkillContentUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> skill_to_response:
    """
    Update the full content of a skill.

    System skills cannot be modified directly. Use tenant skill configs
    to override them instead.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )

    # System skills cannot be modified
    if skill.is_system_skill:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify system skills. Use tenant skill config to override instead.",
        )

    from datetime import datetime

    # Update skill content
    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        trigger_type=skill.trigger_type,
        trigger_patterns=skill.trigger_patterns,
        tools=skill.tools,
        prompt_template=data.full_content,  # Keep in sync
        full_content=data.full_content,
        status=skill.status,
        success_count=skill.success_count,
        failure_count=skill.failure_count,
        created_at=skill.created_at,
        updated_at=datetime.now(UTC),
        metadata=skill.metadata,
        scope=skill.scope,
        is_system_skill=skill.is_system_skill,
    )

    result = await repo.update(updated_skill)
    await db.commit()

    logger.info(f"Skill content updated: {skill_id}")
    return skill_to_response(result)


# === Version History Endpoints ===


class SkillVersionResponse(BaseModel):
    """Schema for skill version response."""

    id: str
    skill_id: str
    version_number: int
    version_label: str | None
    change_summary: str | None
    created_by: str
    created_at: str


class SkillVersionDetailResponse(SkillVersionResponse):
    """Schema for skill version detail (includes content)."""

    skill_md_content: str
    resource_files: dict[str, Any] | None = None


class SkillVersionListResponse(BaseModel):
    """Schema for skill version list response."""

    versions: list[SkillVersionResponse]
    total: int


class SkillRollbackRequest(BaseModel):
    """Schema for skill rollback request."""

    version_number: int = Field(..., ge=1, description="Version number to rollback to")


@router.get(
    "/{skill_id}/versions",
    response_model=SkillVersionListResponse,
    summary="List skill versions",
)
async def list_skill_versions(
    skill_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    tenant: dict = Depends(get_current_user_tenant),
) -> SkillVersionListResponse:
    """List all versions of a skill, ordered by version_number DESC."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    version_repo = SqlSkillVersionRepository(db)
    versions = await version_repo.list_by_skill(skill_id, limit=limit, offset=offset)
    total = await version_repo.count_by_skill(skill_id)

    return SkillVersionListResponse(
        versions=[
            SkillVersionResponse(
                id=v.id,
                skill_id=v.skill_id,
                version_number=v.version_number,
                version_label=v.version_label,
                change_summary=v.change_summary,
                created_by=v.created_by,
                created_at=v.created_at.isoformat(),
            )
            for v in versions
        ],
        total=total,
    )


@router.get(
    "/{skill_id}/versions/{version_number}",
    response_model=SkillVersionDetailResponse,
    summary="Get skill version detail",
)
async def get_skill_version(
    skill_id: str,
    version_number: int,
    db: AsyncSession = Depends(get_db),
    tenant: dict = Depends(get_current_user_tenant),
) -> SkillVersionDetailResponse:
    """Get a specific version of a skill including content and resource files."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    version_repo = SqlSkillVersionRepository(db)
    version = await version_repo.get_by_version(skill_id, version_number)

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found for skill {skill_id}",
        )

    return SkillVersionDetailResponse(
        id=version.id,
        skill_id=version.skill_id,
        version_number=version.version_number,
        version_label=version.version_label,
        skill_md_content=version.skill_md_content,
        resource_files=version.resource_files,
        change_summary=version.change_summary,
        created_by=version.created_by,
        created_at=version.created_at.isoformat(),
    )


@router.post(
    "/{skill_id}/rollback",
    response_model=SkillResponse,
    summary="Rollback skill to a previous version",
)
async def rollback_skill(
    skill_id: str,
    request_body: SkillRollbackRequest,
    db: AsyncSession = Depends(get_db),
    tenant: dict = Depends(get_current_user_tenant),
) -> skill_to_response:
    """Rollback a skill to a specific version. Creates a new version entry."""
    from pathlib import Path

    from src.application.services.skill_reverse_sync import SkillReverseSync
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    skill_repo = SqlSkillRepository(db)
    version_repo = SqlSkillVersionRepository(db)

    # Verify skill exists and belongs to tenant
    skill = await skill_repo.get_by_id(skill_id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill not found: {skill_id}",
        )

    tenant_id = tenant["tenant_id"]
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    reverse_sync = SkillReverseSync(
        skill_repository=skill_repo,
        skill_version_repository=version_repo,
        host_project_path=Path.cwd(),
    )

    result = await reverse_sync.rollback_to_version(
        skill_id=skill_id,
        version_number=request_body.version_number,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    await db.commit()

    # Return updated skill
    updated_skill = await skill_repo.get_by_id(skill_id)
    return skill_to_response(updated_skill)
