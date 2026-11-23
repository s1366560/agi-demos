# pyright: reportImportCycles=false
"""Authoritative desktop tenant/project context endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from src.application.schemas.workspace_context import (
    WorkspaceContextResponse,
    WorkspaceContextSwitchRequest as WorkspaceContextSwitchRequestSchema,
    WorkspaceContextSwitchResponse,
)
from src.domain.model.auth.workspace_context import (
    WorkspaceContextSwitchRequest,
)
from src.host.identity.workspace_context import (
    read_response,
    switch_response,
)
from src.infrastructure.adapters.primary.web.dependencies import verify_api_key_dependency
from src.infrastructure.adapters.primary.web.workspace_context_application_authority_v2 import (
    WorkspaceContextApplicationAuthorityV2,
    workspace_context_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey

router = APIRouter(prefix="/api/v1/workspace-context", tags=["workspace-context"])


@router.get("", response_model=WorkspaceContextResponse)
async def get_workspace_context(
    workspace_context_application: WorkspaceContextApplicationAuthorityV2 = Depends(
        workspace_context_application_authority_dependency_v2
    ),
    api_key: APIKey = Depends(verify_api_key_dependency),
) -> WorkspaceContextResponse:
    _ = api_key
    return await read_response(
        workspace_context_application.db,
        workspace_context_application.services.context.get_or_initialize(
            user_id=str(workspace_context_application.api_key.user_id),
            observed_at=datetime.now(UTC),
        ),
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
    return await switch_response(
        workspace_context_application.db,
        workspace_context_application.services.context.switch(
            user_id=str(workspace_context_application.api_key.user_id),
            actor_api_key_id=str(workspace_context_application.api_key.id),
            request=WorkspaceContextSwitchRequest(**body.model_dump()),
            observed_at=datetime.now(UTC),
        ),
    )
