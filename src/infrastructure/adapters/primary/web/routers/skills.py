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
from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.i18n import gettext as _


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.
    """
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container.redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/skills", tags=["Skills"])


# === Pydantic Models ===


class SkillCreate(BaseModel):
    """Schema for creating a new skill."""

    name: str = Field(..., min_length=1, max_length=200, description="Skill name")
    description: str = Field(..., min_length=1, description="Skill description")
    tools: list[str] = Field(..., min_length=1, description="List of tool names")
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
    tools: list[str] | None = Field(None, min_length=1)
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
    tools: list[str]
    full_content: str | None = None
    status: str
    scope: str
    is_system_skill: bool = False
    created_at: str
    updated_at: str
    metadata: dict[str, Any] | None
    current_version: int = 0
    version_label: str | None = None
    # P2-4 curated lineage
    parent_curated_id: str | None = None
    semver: str | None = None
    revision_hash: str | None = None


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
        tools=list(skill.tools),
        full_content=skill.full_content,
        status=skill.status.value,
        scope=skill.scope.value,
        is_system_skill=skill.is_system_skill,
        created_at=skill.created_at.isoformat(),
        updated_at=skill.updated_at.isoformat(),
        metadata=skill.metadata,
        current_version=getattr(skill, "current_version", 0),
        version_label=getattr(skill, "version_label", None),
        parent_curated_id=getattr(skill, "parent_curated_id", None),
        semver=getattr(skill, "semver", None),
        revision_hash=getattr(skill, "revision_hash", None),
    )


def _invalid_skill_request_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("Invalid skill request"),
    )


def _skill_version_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Skill version not found"),
    )


# === API Endpoints ===


@router.post("/", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: Request,
    data: SkillCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
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
                detail=_("Invalid skill scope"),
            ) from None

        if scope == SkillScope.SYSTEM:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("Cannot create system-level skills via API"),
            )

        if scope == SkillScope.PROJECT and not data.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("project_id is required for project-scoped skills"),
            )

        container = get_container_with_db(request, db)

        # Create skill
        skill = Skill.create(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            tools=data.tools,
            project_id=data.project_id,
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
        raise _invalid_skill_request_error() from e


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
) -> SkillResponse:
    """
    Get a specific skill by ID.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    return skill_to_response(skill)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    request: Request,
    skill_id: str,
    data: SkillUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """
    Update an existing skill.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Update fields
    from datetime import datetime

    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,  # project_id cannot be changed
        name=data.name if data.name else skill.name,
        description=data.description if data.description else skill.description,
        tools=data.tools if data.tools else skill.tools,
        status=SkillStatus(data.status) if data.status else skill.status,
        created_at=skill.created_at,
        updated_at=datetime.now(UTC),
        metadata=data.metadata if data.metadata is not None else skill.metadata,
        full_content=data.full_content if data.full_content is not None else skill.full_content,
        scope=skill.scope,
        is_system_skill=skill.is_system_skill,
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
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    await repo.delete(skill_id)
    await db.commit()

    logger.info(f"Skill deleted: {skill_id}")


@router.patch("/{skill_id}/status")
async def update_skill_status(
    request: Request,
    skill_id: str,
    status_value: str = Query(..., alias="status", description="New status"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """
    Update skill status (active, disabled, deprecated).
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    try:
        new_status = SkillStatus(status_value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid skill status"),
        ) from None

    from datetime import datetime

    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        tools=skill.tools,
        full_content=skill.full_content,
        status=new_status,
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
            detail=_("Skill not found"),
        )

    # Verify tenant access (system skills are accessible to all tenants)
    if not skill.is_system_skill and skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    return SkillContentResponse(
        skill_id=skill.id,
        name=skill.name,
        full_content=skill.full_content,
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
) -> SkillResponse:
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
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # System skills cannot be modified
    if skill.is_system_skill:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Cannot modify system skills. Use tenant skill config to override instead."),
        )

    from datetime import datetime

    # Update skill content
    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        tools=skill.tools,
        full_content=data.full_content,
        status=skill.status,
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
    tenant: dict[str, Any] = Depends(get_current_user_tenant),
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
    tenant: dict[str, Any] = Depends(get_current_user_tenant),
) -> SkillVersionDetailResponse:
    """Get a specific version of a skill including content and resource files."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    version_repo = SqlSkillVersionRepository(db)
    version = await version_repo.get_by_version(skill_id, version_number)

    if not version:
        raise _skill_version_not_found_error()

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
    tenant: dict[str, Any] = Depends(get_current_user_tenant),
) -> SkillResponse:
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
            detail=_("Skill not found"),
        )

    tenant_id = tenant["tenant_id"]
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
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
            detail=_("Skill rollback failed"),
        )

    await db.commit()

    # Return updated skill
    updated_skill = await skill_repo.get_by_id(skill_id)
    assert updated_skill is not None
    return skill_to_response(updated_skill)
