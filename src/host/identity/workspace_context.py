"""Persist and expose the authenticated user's project selection on the standalone host."""

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Annotated, Never

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_context import (
    WorkspaceContextResponse,
    WorkspaceContextSnapshotResponse,
    WorkspaceContextSwitchRequest as SwitchBody,
    WorkspaceContextSwitchResponse,
)
from src.domain.model.auth.workspace_context import (
    WorkspaceContextAccess,
    WorkspaceContextError,
    WorkspaceContextErrorCode,
    WorkspaceContextSnapshot,
    WorkspaceContextSwitchOutcome,
    WorkspaceContextSwitchRequest,
)
from src.host.identity.workspace_selection import get_or_initialize
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    verify_api_key_dependency,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import APIKey
from src.infrastructure.adapters.secondary.persistence.sql_desktop_workspace_context_repository import (
    SqlDesktopWorkspaceContextRepository,
)

router = APIRouter(prefix="/api/v1/workspace-context", tags=["Identity"])
Database = Annotated[AsyncSession, Depends(get_db)]
Credential = Annotated[APIKey, Depends(verify_api_key_dependency)]


def snapshot_response(snapshot: WorkspaceContextSnapshot) -> WorkspaceContextSnapshotResponse:
    return WorkspaceContextSnapshotResponse.model_validate(snapshot, from_attributes=True)


def raise_context_error(error: WorkspaceContextError) -> Never:
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


async def read_response(
    db: AsyncSession, operation: Awaitable[WorkspaceContextAccess]
) -> WorkspaceContextResponse:
    try:
        access = await operation
    except WorkspaceContextError as error:
        raise_context_error(error)
    await db.commit()
    return WorkspaceContextResponse(
        context=snapshot_response(access.context), membership_role=access.membership_role
    )


async def switch_response(
    db: AsyncSession, operation: Awaitable[WorkspaceContextSwitchOutcome]
) -> WorkspaceContextSwitchResponse:
    try:
        outcome = await operation
    except WorkspaceContextError as error:
        raise_context_error(error)
    await db.commit()
    return WorkspaceContextSwitchResponse(
        context=snapshot_response(outcome.context), changed=outcome.changed
    )


@router.get("")
async def read_context(db: Database, key: Credential) -> WorkspaceContextResponse:
    repository = SqlDesktopWorkspaceContextRepository(db, require_tenant_membership=True)
    return await read_response(db, get_or_initialize(repository, key.user_id, datetime.now(UTC)))


@router.post("/switch")
async def switch_context(
    body: SwitchBody, db: Database, key: Credential
) -> WorkspaceContextSwitchResponse:
    repository = SqlDesktopWorkspaceContextRepository(db, require_tenant_membership=True)
    return await switch_response(
        db,
        repository.switch(
            key.user_id,
            actor_api_key_id=key.id,
            request=WorkspaceContextSwitchRequest(**body.model_dump()),
            observed_at=datetime.now(UTC),
        ),
    )
