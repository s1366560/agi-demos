# pyright: reportImportCycles=false
"""Authoritative desktop tenant/project context endpoints."""

from datetime import UTC, datetime
from typing import Never

from fastapi import APIRouter, Depends, HTTPException, status

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
from src.infrastructure.adapters.primary.web.workspace_context_application_authority_v2 import (
    WorkspaceContextApplicationAuthorityV2,
    workspace_context_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey

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
    workspace_context_application: WorkspaceContextApplicationAuthorityV2 = Depends(
        workspace_context_application_authority_dependency_v2
    ),
    api_key: APIKey = Depends(verify_api_key_dependency),
) -> WorkspaceContextResponse:
    _ = api_key
    try:
        access = await workspace_context_application.services.context.get_or_initialize(
            user_id=str(workspace_context_application.api_key.user_id),
            observed_at=datetime.now(UTC),
        )
    except WorkspaceContextError as error:
        _raise_workspace_context_http_error(error)
    await workspace_context_application.db.commit()
    return WorkspaceContextResponse(
        context=_snapshot_response(access.context),
        membership_role=access.membership_role,
    )


@router.post("/switch", response_model=WorkspaceContextSwitchResponse)
async def switch_workspace_context(
    body: WorkspaceContextSwitchRequestSchema,
    workspace_context_application: WorkspaceContextApplicationAuthorityV2 = Depends(
        workspace_context_application_authority_dependency_v2
    ),
    api_key: APIKey = Depends(verify_api_key_dependency),
) -> WorkspaceContextSwitchResponse:
    _ = api_key
    try:
        outcome = await workspace_context_application.services.context.switch(
            user_id=str(workspace_context_application.api_key.user_id),
            actor_api_key_id=str(workspace_context_application.api_key.id),
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
    await workspace_context_application.db.commit()
    return WorkspaceContextSwitchResponse(
        context=_snapshot_response(outcome.context),
        changed=outcome.changed,
    )
