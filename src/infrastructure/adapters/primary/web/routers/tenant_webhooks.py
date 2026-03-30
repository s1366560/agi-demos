from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.utils import get_container_with_db
from src.infrastructure.adapters.secondary.persistence.database import get_db

router = APIRouter(prefix="/tenant-webhooks", tags=["Webhooks"])


class WebhookCreateRequest(BaseModel):
    name: str
    url: str
    events: list[str]
    is_active: bool = True


class WebhookUpdateRequest(BaseModel):
    name: str
    url: str
    events: list[str]
    is_active: bool


class WebhookResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    url: str
    secret: str | None
    events: list[str]
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None


@router.post("/{tenant_id}", response_model=WebhookResponse)
async def create_webhook(
    tenant_id: str,
    body: WebhookCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    container = get_container_with_db(request, db)
    service = container.webhook_service()

    webhook = await service.create_webhook(
        tenant_id=tenant_id,
        name=body.name,
        url=body.url,
        events=body.events,
        is_active=body.is_active,
    )
    await db.commit()
    return webhook


@router.get("/{tenant_id}", response_model=list[WebhookResponse])
async def list_webhooks(
    tenant_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    container = get_container_with_db(request, db)
    service = container.webhook_service()

    return await service.list_webhooks(tenant_id)


@router.put("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: str,
    body: WebhookUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    container = get_container_with_db(request, db)
    service = container.webhook_service()

    try:
        webhook = await service.update_webhook(
            webhook_id=webhook_id,
            name=body.name,
            url=body.url,
            events=body.events,
            is_active=body.is_active,
        )
        await db.commit()
        return webhook
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    container = get_container_with_db(request, db)
    service = container.webhook_service()

    deleted = await service.delete_webhook(webhook_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    await db.commit()
    return None
