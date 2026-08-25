from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/messages",
    tags=["workspace-chat"],
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


@router.post("", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    raise workspace_core_unavailable_error()


@router.get("", response_model=MessageListResponse)
async def list_messages(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None),
    current_user: User = Depends(get_current_user),
) -> MessageListResponse:
    raise workspace_core_unavailable_error()


@router.get("/mentions/{target_id}", response_model=MessageListResponse)
async def get_mentions(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    target_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> MessageListResponse:
    raise workspace_core_unavailable_error()
