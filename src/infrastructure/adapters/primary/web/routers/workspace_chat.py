from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_message_service import WorkspaceMessageService
from src.application.services.workspace_surface_contract import (
    SIGNAL_ROLE_KEY,
    SURFACE_BOUNDARY_KEY,
    WORKSPACE_CHAT_EVENT_METADATA,
)
from src.domain.model.workspace.workspace_message import MessageSenderType, WorkspaceMessage
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_access import (
    require_workspace_access,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/messages",
    tags=["workspace-chat"],
)


def get_message_service(
    request: Request, db: AsyncSession = Depends(get_db)
) -> WorkspaceMessageService:
    container = request.app.state.container.with_db(db)
    redis_client = container.redis_client

    async def _publish_event(workspace_id: str, event_name: str, payload: dict[str, Any]) -> None:
        from src.domain.events.types import AgentEventType
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event_with_retry,
        )

        event_type = AgentEventType(event_name)
        await publish_workspace_event_with_retry(
            redis_client,
            workspace_id=workspace_id,
            event_type=event_type,
            payload={
                **payload,
                SURFACE_BOUNDARY_KEY: WORKSPACE_CHAT_EVENT_METADATA[SURFACE_BOUNDARY_KEY],
                SIGNAL_ROLE_KEY: WORKSPACE_CHAT_EVENT_METADATA[SIGNAL_ROLE_KEY],
            },
            metadata=dict(WORKSPACE_CHAT_EVENT_METADATA),
        )

    return cast(
        WorkspaceMessageService,
        container.workspace_message_service(
            workspace_event_publisher=_publish_event if redis_client is not None else None,
        ),
    )


async def _publish_pending_chat_events_after_failure(
    service: WorkspaceMessageService,
    *,
    workspace_id: str,
) -> None:
    try:
        await service.publish_pending_events()
    except Exception:
        logger.exception(
            "Failed to publish workspace chat events after background retry",
            extra={"workspace_id": workspace_id},
        )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_("Access denied"))
    if isinstance(exc, ValueError):
        message = str(exc)
        if "not found" in message.lower():
            return HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_("Workspace message not found"),
            )
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid workspace chat request"),
        )
    logger.exception("Workspace chat route failed")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=_("Internal server error"),
    )


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    sender_type: str = Field(default="human")
    parent_message_id: str | None = None
    mentions: list[str] = Field(default_factory=list)


class MessageResponse(BaseModel):
    id: str
    workspace_id: str
    sender_id: str
    sender_type: str
    content: str
    mentions: list[str]
    parent_message_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]


def _to_response(msg: WorkspaceMessage) -> MessageResponse:
    return MessageResponse(
        id=msg.id,
        workspace_id=msg.workspace_id,
        sender_id=msg.sender_id,
        sender_type=msg.sender_type.value,
        content=msg.content,
        mentions=msg.mentions,
        parent_message_id=msg.parent_message_id,
        metadata=msg.metadata,
        created_at=msg.created_at,
    )


@router.post("", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: SendMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await require_workspace_access(
        db,
        current_user,
        tenant_id,
        project_id,
        workspace_id,
        require_editor=True,
    )
    service = get_message_service(request, db)
    try:
        sender_type = MessageSenderType(payload.sender_type)
        if sender_type != MessageSenderType.HUMAN:
            raise ValueError("sender_type must be human")
        message = await service.send_message(
            workspace_id=workspace_id,
            sender_id=current_user.id,
            sender_type=sender_type,
            sender_name=current_user.email,
            content=payload.content,
            parent_message_id=payload.parent_message_id,
            mentions=payload.mentions,
        )
        await db.commit()
        try:
            await service.publish_pending_events()
        except Exception:
            logger.exception(
                "Failed to publish workspace chat events",
                extra={"workspace_id": workspace_id},
            )
            background_tasks.add_task(
                _publish_pending_chat_events_after_failure,
                service,
                workspace_id=workspace_id,
            )

        if message.mentions:
            _fire_mention_routing(
                request=request,
                workspace_id=workspace_id,
                message=message,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=current_user.id,
            )

        return _to_response(message)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


def _fire_mention_routing(
    request: Request | None,
    workspace_id: str,
    message: WorkspaceMessage,
    tenant_id: str,
    project_id: str,
    user_id: str,
) -> None:
    del request, workspace_id, message, tenant_id, project_id, user_id
    logger.debug("Legacy Python Workspace mention routing is retired; Core owns dispatch")


@router.get("", response_model=MessageListResponse)
async def list_messages(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    await require_workspace_access(db, current_user, tenant_id, project_id, workspace_id)
    service = get_message_service(request, db)
    try:
        messages = await service.list_messages(
            workspace_id=workspace_id,
            limit=limit,
            before=before,
        )
        return MessageListResponse(items=[_to_response(msg) for msg in messages])
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/mentions/{target_id}", response_model=MessageListResponse)
async def get_mentions(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    target_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    await require_workspace_access(db, current_user, tenant_id, project_id, workspace_id)
    service = get_message_service(request, db)
    try:
        messages = await service.get_mentions(
            workspace_id=workspace_id,
            target_id=target_id,
            limit=limit,
        )
        return MessageListResponse(items=[_to_response(msg) for msg in messages])
    except Exception as exc:
        raise _map_error(exc) from exc
