"""Authoritative desktop tenant/project context endpoints."""

from datetime import UTC, datetime
from typing import Never

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_context import (
    WorkspaceContextResponse,
    WorkspaceContextSnapshotResponse,
    WorkspaceContextSwitchRequest as WorkspaceContextSwitchRequestSchema,
    WorkspaceContextSwitchResponse,
)
from src.domain.model.auth.workspace_context import (
    WorkspaceContextError,
    WorkspaceContextErrorCode,
    WorkspaceContextSnapshot,
    WorkspaceContextSwitchRequest,
)
from src.infrastructure.adapters.primary.web.dependencies import verify_api_key_dependency
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import APIKey
from src.infrastructure.adapters.secondary.persistence.sql_desktop_workspace_context_repository import (
    SqlDesktopWorkspaceContextRepository,
)

router = APIRouter(prefix="/api/v1/workspace-context", tags=["workspace-context"])


def _snapshot_response(snapshot: WorkspaceContextSnapshot) -> WorkspaceContextSnapshotResponse:
    return WorkspaceContextSnapshotResponse(
        tenant_id=snapshot.tenant_id,
        project_id=snapshot.project_id,
        revision=snapshot.revision,
        updated_at=snapshot.updated_at,
    )


def _raise_workspace_context_http_error(error: WorkspaceContextError) -> Never:
    status_by_code = {
        WorkspaceContextErrorCode.INVALID_INPUT: status.HTTP_422_UNPROCESSABLE_ENTITY,
        WorkspaceContextErrorCode.UNAVAILABLE: status.HTTP_404_NOT_FOUND,
        WorkspaceContextErrorCode.MEMBERSHIP_REQUIRED: status.HTTP_403_FORBIDDEN,
        WorkspaceContextErrorCode.PROJECT_UNAVAILABLE: status.HTTP_403_FORBIDDEN,
        WorkspaceContextErrorCode.REVISION_CONFLICT: status.HTTP_409_CONFLICT,
        WorkspaceContextErrorCode.IDEMPOTENCY_CONFLICT: status.HTTP_409_CONFLICT,
        WorkspaceContextErrorCode.REVISION_EXHAUSTED: status.HTTP_409_CONFLICT,
    }
    detail: dict[str, str | int] = {"code": error.code.value}
    if error.expected_revision is not None:
        detail["expected_revision"] = error.expected_revision
    if error.actual_revision is not None:
        detail["actual_revision"] = error.actual_revision
    raise HTTPException(status_code=status_by_code[error.code], detail=detail) from error


@router.get("", response_model=WorkspaceContextResponse)
async def get_workspace_context(
    api_key: APIKey = Depends(verify_api_key_dependency),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceContextResponse:
    repository = SqlDesktopWorkspaceContextRepository(db)
    try:
        access = await repository.get_or_initialize(api_key.user_id, datetime.now(UTC))
    except WorkspaceContextError as error:
        _raise_workspace_context_http_error(error)
    await db.commit()
    return WorkspaceContextResponse(
        context=_snapshot_response(access.context),
        membership_role=access.membership_role,
    )


@router.post("/switch", response_model=WorkspaceContextSwitchResponse)
async def switch_workspace_context(
    body: WorkspaceContextSwitchRequestSchema,
    api_key: APIKey = Depends(verify_api_key_dependency),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceContextSwitchResponse:
    repository = SqlDesktopWorkspaceContextRepository(db)
    try:
        outcome = await repository.switch(
            api_key.user_id,
            actor_api_key_id=api_key.id,
            request=WorkspaceContextSwitchRequest(
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                expected_revision=body.expected_revision,
                idempotency_key=body.idempotency_key,
            ),
            observed_at=datetime.now(UTC),
        )
    except WorkspaceContextError as error:
        _raise_workspace_context_http_error(error)
    await db.commit()
    return WorkspaceContextSwitchResponse(
        context=_snapshot_response(outcome.context),
        changed=outcome.changed,
    )
