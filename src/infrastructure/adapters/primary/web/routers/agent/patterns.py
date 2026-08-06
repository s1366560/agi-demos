"""Workflow patterns endpoints for Agent API.

Provides CRUD operations for workflow patterns:
- list_patterns: List patterns for a tenant
- get_pattern: Get a single pattern by ID
- delete_pattern: Delete a pattern (admin only)
- reset_patterns: Reset all patterns for a tenant (admin only)
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project as DBProject,
    UserProject as DBUserProject,
    UserTenant as DBUserTenant,
)
from src.infrastructure.i18n import gettext as _

from .access import _get_user_id, require_tenant_access
from .schemas import (
    PatternsListResponse,
    PatternStepResponse,
    ProjectPatternsListResponse,
    ResetPatternsResponse,
    WorkflowPatternResponse,
)
from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/workflows/patterns/project/{project_id}",
    response_model=ProjectPatternsListResponse,
)
async def list_project_shared_patterns(
    project_id: str,
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    min_success_rate: float | None = Query(
        None,
        ge=0,
        le=1,
        description="Minimum success rate filter",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectPatternsListResponse:
    """List tenant-shared patterns available to an explicitly authorized project member."""
    project_result = await db.execute(
        refresh_select_statement(select(DBProject.tenant_id).where(DBProject.id == project_id))
    )
    tenant_id = project_result.scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(status_code=404, detail=_("Project not found"))

    user_id = _get_user_id(current_user)
    membership_result = await db.execute(
        refresh_select_statement(
            select(DBUserProject.id)
            .join(
                DBUserTenant,
                (DBUserTenant.user_id == DBUserProject.user_id)
                & (DBUserTenant.tenant_id == tenant_id),
            )
            .where(
                DBUserProject.user_id == user_id,
                DBUserProject.project_id == project_id,
            )
            .limit(1)
        )
    )
    if membership_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail=_("Project access required"))

    try:
        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()
        all_patterns = await pattern_repo.list_by_tenant(tenant_id)
        if min_success_rate is not None:
            all_patterns = [
                pattern for pattern in all_patterns if pattern.success_rate >= min_success_rate
            ]
        total = len(all_patterns)
        start_idx = (page - 1) * page_size
        paginated_patterns = all_patterns[start_idx : start_idx + page_size]
        return ProjectPatternsListResponse(
            project_id=project_id,
            tenant_id=tenant_id,
            patterns=[_pattern_response(pattern) for pattern in paginated_patterns],
            total=total,
            page=page,
            page_size=page_size,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error listing tenant-shared patterns for project")
        raise HTTPException(status_code=500, detail=_("Failed to list patterns")) from exc


def _pattern_response(pattern: Any) -> WorkflowPatternResponse:  # noqa: ANN401
    return WorkflowPatternResponse(
        id=pattern.id,
        tenant_id=pattern.tenant_id,
        name=pattern.name,
        description=pattern.description,
        steps=[
            PatternStepResponse(
                step_number=step.step_number,
                description=step.description,
                tool_name=step.tool_name,
                expected_output_format=step.expected_output_format,
                similarity_threshold=step.similarity_threshold,
                tool_parameters=step.tool_parameters,
            )
            for step in pattern.steps
        ],
        success_rate=pattern.success_rate,
        usage_count=pattern.usage_count,
        created_at=pattern.created_at.isoformat(),
        updated_at=pattern.updated_at.isoformat(),
        metadata=pattern.metadata,
    )


@router.get("/workflows/patterns", response_model=PatternsListResponse)
async def list_patterns(
    request: Request,
    tenant_id: str = Query(..., description="Tenant ID to filter patterns"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    min_success_rate: float | None = Query(
        None, ge=0, le=1, description="Minimum success rate filter"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PatternsListResponse:
    """
    List workflow patterns for a tenant (T080).

    Patterns are tenant-scoped and shared across all projects within the tenant.
    Non-admin users have read-only access (FR-019).
    """
    try:
        await require_tenant_access(db, current_user, tenant_id)

        assert request is not None
        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        # Get all patterns for tenant
        all_patterns = await pattern_repo.list_by_tenant(tenant_id)

        # Apply optional success rate filter
        if min_success_rate is not None:
            all_patterns = [p for p in all_patterns if p.success_rate >= min_success_rate]

        # Apply pagination
        total = len(all_patterns)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_patterns = all_patterns[start_idx:end_idx]

        return PatternsListResponse(
            patterns=[
                WorkflowPatternResponse(
                    id=p.id,
                    tenant_id=p.tenant_id,
                    name=p.name,
                    description=p.description,
                    steps=[
                        PatternStepResponse(
                            step_number=s.step_number,
                            description=s.description,
                            tool_name=s.tool_name,
                            expected_output_format=s.expected_output_format,
                            similarity_threshold=s.similarity_threshold,
                            tool_parameters=s.tool_parameters,
                        )
                        for s in p.steps
                    ],
                    success_rate=p.success_rate,
                    usage_count=p.usage_count,
                    created_at=p.created_at.isoformat(),
                    updated_at=p.updated_at.isoformat(),
                    metadata=p.metadata,
                )
                for p in paginated_patterns
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error listing patterns")
        raise HTTPException(status_code=500, detail=_("Failed to list patterns")) from exc


@router.get("/workflows/patterns/{pattern_id}", response_model=WorkflowPatternResponse)
async def get_pattern(
    pattern_id: str,
    request: Request,
    tenant_id: str = Query(..., description="Tenant ID for authorization"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowPatternResponse:
    """
    Get a workflow pattern by ID (T081).
    """
    try:
        await require_tenant_access(db, current_user, tenant_id)

        assert request is not None
        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        pattern = await pattern_repo.get_by_id(pattern_id)

        if not pattern:
            raise HTTPException(status_code=404, detail=_("Pattern not found"))

        # Verify pattern belongs to the tenant
        if pattern.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail=_("Pattern not found"))

        return WorkflowPatternResponse(
            id=pattern.id,
            tenant_id=pattern.tenant_id,
            name=pattern.name,
            description=pattern.description,
            steps=[
                PatternStepResponse(
                    step_number=s.step_number,
                    description=s.description,
                    tool_name=s.tool_name,
                    expected_output_format=s.expected_output_format,
                    similarity_threshold=s.similarity_threshold,
                    tool_parameters=s.tool_parameters,
                )
                for s in pattern.steps
            ],
            success_rate=pattern.success_rate,
            usage_count=pattern.usage_count,
            created_at=pattern.created_at.isoformat(),
            updated_at=pattern.updated_at.isoformat(),
            metadata=pattern.metadata,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting pattern")
        raise HTTPException(status_code=500, detail=_("Failed to get pattern")) from exc


@router.delete("/workflows/patterns/{pattern_id}", status_code=200)
async def delete_pattern(
    pattern_id: str,
    request: Request,
    tenant_id: str = Query(..., description="Tenant ID for authorization"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Delete a workflow pattern by ID (T082) - Admin only.
    """
    try:
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)

        assert request is not None
        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        # Check if pattern exists
        pattern = await pattern_repo.get_by_id(pattern_id)
        if not pattern:
            raise HTTPException(status_code=404, detail=_("Pattern not found"))
        if pattern.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail=_("Pattern not found"))

        # Delete pattern
        deleted = await pattern_repo.delete(pattern_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=_("Pattern not found"))

        return {"message": "Pattern deleted successfully", "pattern_id": pattern_id}

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error deleting pattern")
        raise HTTPException(status_code=500, detail=_("Failed to delete pattern")) from exc


@router.post("/workflows/patterns/reset", response_model=ResetPatternsResponse)
async def reset_patterns(
    request: Request,
    tenant_id: str = Query(..., description="Tenant ID to reset patterns for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResetPatternsResponse:
    """
    Reset/delete all workflow patterns for a tenant (T083) - Admin only.
    """
    try:
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)

        assert request is not None
        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        # Get all patterns for tenant
        all_patterns = await pattern_repo.list_by_tenant(tenant_id)

        # Delete all patterns
        deleted_count = 0
        for pattern in all_patterns:
            deleted = await pattern_repo.delete(pattern.id)
            if deleted:
                deleted_count += 1

        return ResetPatternsResponse(
            deleted_count=deleted_count,
            tenant_id=tenant_id,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error resetting patterns")
        raise HTTPException(status_code=500, detail=_("Failed to reset patterns")) from exc
