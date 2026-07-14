"""Scoped cloud conversation session projection endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.conversation_session_projection import (
    ConversationSessionProjectionResponse,
)
from src.application.services.conversation_session_projection_service import (
    ConversationSessionNotFoundError,
    ConversationSessionProjectionService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_conversation_session_projection_reader import (
    SqlConversationSessionProjectionReader,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter()


@router.get(
    "/conversations/{conversation_id}/session",
    response_model=ConversationSessionProjectionResponse,
)
async def get_conversation_session_projection(
    conversation_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    workspace_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationSessionProjectionResponse:
    """Return one exact-scope persisted session projection for the current user."""

    service = ConversationSessionProjectionService(SqlConversationSessionProjectionReader(db))
    try:
        return await service.get_projection(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=current_user.id,
        )
    except ConversationSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_("Conversation not found")) from exc


__all__ = ["router"]
