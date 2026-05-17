from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.primary.web.routers.agent.utils import get_container_with_db
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.i18n import gettext as _

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


async def _require_webhook_tenant_admin(
    webhook_id: str,
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> None:
    container = get_container_with_db(request, db)
    service = container.webhook_service()

    webhook = await service.get_webhook(webhook_id)
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Webhook not found"))

    await require_tenant_access(db, current_user, webhook.tenant_id, require_admin=True)


@router.post("/{tenant_id}", response_model=WebhookResponse)
async def create_webhook(
    tenant_id: str,
    body: WebhookCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    await require_tenant_access(db, current_user, tenant_id, require_admin=True)
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
    return cast(WebhookResponse, webhook)


@router.get("/{tenant_id}", response_model=list[WebhookResponse])
async def list_webhooks(
    tenant_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookResponse]:
    await require_tenant_access(db, current_user, tenant_id, require_admin=True)
    container = get_container_with_db(request, db)
    service = container.webhook_service()

    return cast(list[WebhookResponse], await service.list_webhooks(tenant_id))


@router.put("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: str,
    body: WebhookUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    await _require_webhook_tenant_admin(webhook_id, request, current_user, db)
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
        return cast(WebhookResponse, webhook)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Webhook not found"),
        ) from e


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_webhook_tenant_admin(webhook_id, request, current_user, db)
    container = get_container_with_db(request, db)
    service = container.webhook_service()

    deleted = await service.delete_webhook(webhook_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Webhook not found"))
    await db.commit()
    return None
