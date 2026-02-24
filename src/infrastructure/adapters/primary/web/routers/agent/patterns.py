"""Workflow patterns endpoints for Agent API.

Provides CRUD operations for workflow patterns:
- list_patterns: List patterns for a tenant
- get_pattern: Get a single pattern by ID
- delete_pattern: Delete a pattern (admin only)
- reset_patterns: Reset all patterns for a tenant (admin only)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .schemas import (
    PatternsListResponse,
    PatternStepResponse,
    ResetPatternsResponse,
    WorkflowPatternResponse,
)
from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/workflows/patterns", response_model=PatternsListResponse)
async def list_patterns(
    tenant_id: str = Query(..., description="Tenant ID to filter patterns"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    min_success_rate: float | None = Query(
        None, ge=0, le=1, description="Minimum success rate filter"
    ),
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PatternsListResponse:
    """
    List workflow patterns for a tenant (T080).

    Patterns are tenant-scoped and shared across all projects within the tenant.
    Non-admin users have read-only access (FR-019).
    """
    try:
        # Verify tenant access
        if user_tenant_id != tenant_id and not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Access denied to tenant patterns")

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
    except Exception as e:
        logger.error(f"Error listing patterns: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list patterns: {e!s}")


@router.get("/workflows/patterns/{pattern_id}", response_model=WorkflowPatternResponse)
async def get_pattern(
    pattern_id: str,
    tenant_id: str = Query(..., description="Tenant ID for authorization"),
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> WorkflowPatternResponse:
    """
    Get a workflow pattern by ID (T081).
    """
    try:
        # Verify tenant access
        if user_tenant_id != tenant_id and not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Access denied to tenant patterns")

        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        pattern = await pattern_repo.get_by_id(pattern_id)

        if not pattern:
            raise HTTPException(status_code=404, detail="Pattern not found")

        # Verify pattern belongs to the tenant
        if pattern.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Pattern not found")

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
    except Exception as e:
        logger.error(f"Error getting pattern: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get pattern: {e!s}")


@router.delete("/workflows/patterns/{pattern_id}", status_code=200)
async def delete_pattern(
    pattern_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Delete a workflow pattern by ID (T082) - Admin only.
    """
    try:
        # Verify admin access
        if not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required")

        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        # Check if pattern exists
        pattern = await pattern_repo.get_by_id(pattern_id)
        if not pattern:
            raise HTTPException(status_code=404, detail="Pattern not found")

        # Delete pattern
        await pattern_repo.delete(pattern_id)

        return {"message": "Pattern deleted successfully", "pattern_id": pattern_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting pattern: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete pattern: {e!s}")


@router.post("/workflows/patterns/reset", response_model=ResetPatternsResponse)
async def reset_patterns(
    tenant_id: str = Query(..., description="Tenant ID to reset patterns for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ResetPatternsResponse:
    """
    Reset/delete all workflow patterns for a tenant (T083) - Admin only.
    """
    try:
        # Verify admin access
        if not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required")

        container = get_container_with_db(request, db)
        pattern_repo = container.workflow_pattern_repository()

        # Get all patterns for tenant
        all_patterns = await pattern_repo.list_by_tenant(tenant_id)

        # Delete all patterns
        deleted_count = 0
        for pattern in all_patterns:
            await pattern_repo.delete(pattern.id)
            deleted_count += 1

        return ResetPatternsResponse(
            deleted_count=deleted_count,
            tenant_id=tenant_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting patterns: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset patterns: {e!s}")
