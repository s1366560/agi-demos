from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_mention_router import WorkspaceMentionRouter
from src.application.services.workspace_message_service import WorkspaceMessageService
from src.domain.model.workspace.workspace_message import MessageSenderType, WorkspaceMessage
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

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
            publish_workspace_event,
        )

        event_type = AgentEventType(event_name)
        await publish_workspace_event(
            redis_client,
            workspace_id=workspace_id,
            event_type=event_type,
            payload=payload,
        )

    return container.workspace_message_service(
        workspace_event_publisher=_publish_event if redis_client is not None else None,
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        message = str(exc)
        if "not found" in message.lower():
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    sender_type: str = Field(default="human")
    parent_message_id: str | None = None


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    service = get_message_service(request, db)
    try:
        sender_type = MessageSenderType(payload.sender_type)
        message = await service.send_message(
            workspace_id=workspace_id,
            sender_id=current_user.id,
            sender_type=sender_type,
            sender_name=current_user.email,
            content=payload.content,
            parent_message_id=payload.parent_message_id,
        )
        await db.commit()

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
    request: Request,
    workspace_id: str,
    message: WorkspaceMessage,
    tenant_id: str,
    project_id: str,
    user_id: str,
) -> None:
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
        SqlConversationRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
        SqlUserRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
        SqlWorkspaceAgentRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
        SqlWorkspaceMemberRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_message_repository import (
        SqlWorkspaceMessageRepository,
    )

    container = request.app.state.container
    redis_client = container.redis_client

    async def _publish_event(ws_id: str, event_name: str, event_payload: dict[str, Any]) -> None:
        from src.domain.events.types import AgentEventType
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event,
        )

        event_type = AgentEventType(event_name)
        await publish_workspace_event(
            redis_client,
            workspace_id=ws_id,
            event_type=event_type,
            payload=event_payload,
        )

    event_publisher = _publish_event if redis_client is not None else None

    def agent_repo_factory(db: AsyncSession) -> SqlWorkspaceAgentRepository:
        return SqlWorkspaceAgentRepository(db)

    def conversation_repo_factory(db: AsyncSession) -> SqlConversationRepository:
        return SqlConversationRepository(db)

    def agent_service_factory(db: AsyncSession, llm: object) -> object:
        return container.with_db(db).agent_service(llm)

    def message_service_factory(
        db: AsyncSession,
        publisher: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None,
    ) -> WorkspaceMessageService:
        return WorkspaceMessageService(
            message_repo=SqlWorkspaceMessageRepository(db),
            member_repo=SqlWorkspaceMemberRepository(db),
            agent_repo=SqlWorkspaceAgentRepository(db),
            workspace_event_publisher=publisher,
            user_repo=SqlUserRepository(db),
        )

    mention_router = WorkspaceMentionRouter(
        agent_repo_factory=agent_repo_factory,
        agent_service_factory=agent_service_factory,
        message_service_factory=message_service_factory,
        conversation_repo_factory=conversation_repo_factory,
        db_session_factory=async_session_factory,
    )

    mention_router.fire_and_forget(
        workspace_id=workspace_id,
        message=message,
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        event_publisher=event_publisher,
    )


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
