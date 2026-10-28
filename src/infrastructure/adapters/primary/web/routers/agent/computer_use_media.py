"""Authenticated conversation-owned bytes for accepted native REPL media."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # FastAPI resolves annotations at runtime.

from src.application.services.artifact_content_authority_service import (
    ArtifactContentNotReadyError,
    ArtifactContentTooLargeError,
)
from src.application.services.artifact_content_contract import ArtifactContentIntegrityError
from src.domain.model.artifact.artifact import ArtifactStatus
from src.domain.ports.repositories.artifact_content_authority_repository import ArtifactContentScope
from src.infrastructure.adapters.primary.web.artifact_http_application_authority_v2 import (
    ArtifactHttpApplicationAuthorityV2,
    artifact_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Conversation, User
from src.infrastructure.agent.native_computer_use.repl_output import MAX_MEDIA_BYTES, MEDIA_TYPES
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError
from src.infrastructure.i18n import gettext as _

from .computer_use_device import require_project_access

router = APIRouter()


@router.get("/conversations/{conversation_id}/tool-media/{artifact_id}")
async def get_tool_media(
    conversation_id: str,
    artifact_id: str,
    tenant_id: str,
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    artifact_application: ArtifactHttpApplicationAuthorityV2 = Depends(
        artifact_http_application_authority_dependency_v2
    ),
) -> Response:
    try:
        await require_project_access(db, current_user.id, tenant_id, project_id)
    except DeviceBridgeError as error:
        raise HTTPException(status_code=403, detail=_("Tool media access denied")) from error
    conversation = await db.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.tenant_id == tenant_id,
            Conversation.project_id == project_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail=_("Tool media not found"))
    application = artifact_application.services
    artifact = await application.artifacts.get_artifact(artifact_id)
    if (
        artifact is None
        or artifact.tenant_id != tenant_id
        or artifact.project_id != project_id
        or artifact.conversation_id != conversation_id
        or artifact.status != ArtifactStatus.READY
        or artifact.metadata.get("upload_source") != "native_computer_use"
        or artifact.mime_type not in MEDIA_TYPES["image"] | MEDIA_TYPES["audio"]
    ):
        raise HTTPException(status_code=404, detail=_("Tool media not found"))
    scope = ArtifactContentScope(
        artifact_id=artifact_id,
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    try:
        content = await application.content.get_bytes(scope, max_bytes=MAX_MEDIA_BYTES)
    except ArtifactContentNotReadyError as error:
        raise HTTPException(status_code=404, detail=_("Tool media not found")) from error
    except ArtifactContentTooLargeError as error:
        raise HTTPException(status_code=413, detail=_("Tool media exceeds size limit")) from error
    except ArtifactContentIntegrityError as error:
        raise HTTPException(
            status_code=409, detail=_("Tool media integrity check failed")
        ) from error
    if content is None:
        raise HTTPException(status_code=404, detail=_("Tool media not found"))
    if content.mime_type != artifact.mime_type or len(content.content) != artifact.size_bytes:
        raise HTTPException(status_code=409, detail=_("Tool media integrity check failed"))
    await application.commit()
    return Response(
        content=content.content,
        media_type=content.mime_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
