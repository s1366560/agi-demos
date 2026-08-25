from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.domain.model.tenant.webhook import Webhook
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.primary.web.tenant_webhook_application_authority_v2 import (
    TenantWebhookApplicationAuthorityV2,
    tenant_webhook_application_authority_context_v2,
)
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


def _to_webhook_response(webhook: Webhook, *, include_secret: bool) -> WebhookResponse:
    return WebhookResponse(
        id=webhook.id,
        tenant_id=webhook.tenant_id,
        name=webhook.name,
        url=webhook.url,
        secret=webhook.secret if include_secret else None,
        events=list(webhook.events),
        is_active=webhook.is_active,
        created_at=webhook.created_at,
        updated_at=webhook.updated_at,
    )


async def _require_webhook_tenant_admin(
    webhook_id: str,
    authority: TenantWebhookApplicationAuthorityV2,
) -> None:
    service = authority.services.webhooks

    webhook = await service.get_webhook(webhook_id)
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Webhook not found"))

    await require_tenant_access(
        authority.db,
        authority.current_user,
        webhook.tenant_id,
        require_admin=True,
    )


@router.post("/{tenant_id}", response_model=WebhookResponse)
async def create_webhook(
    tenant_id: str,
    body: WebhookCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    async with tenant_webhook_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=tenant_id,
    ) as authority:
        await require_tenant_access(
            authority.db,
            authority.current_user,
            tenant_id,
            require_admin=True,
        )
        webhook = await authority.services.webhooks.create_webhook(
            tenant_id=tenant_id,
            name=body.name,
            url=body.url,
            events=body.events,
            is_active=body.is_active,
        )
        await authority.db.commit()
        return _to_webhook_response(webhook, include_secret=True)


@router.get("/{tenant_id}", response_model=list[WebhookResponse])
async def list_webhooks(
    tenant_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookResponse]:
    async with tenant_webhook_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=tenant_id,
    ) as authority:
        await require_tenant_access(
            authority.db,
            authority.current_user,
            tenant_id,
            require_admin=True,
        )
        webhooks = await authority.services.webhooks.list_webhooks(tenant_id)
        return [_to_webhook_response(webhook, include_secret=False) for webhook in webhooks]


@router.put("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: str,
    body: WebhookUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    async with tenant_webhook_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=None,
    ) as authority:
        await _require_webhook_tenant_admin(webhook_id, authority)
        try:
            webhook = await authority.services.webhooks.update_webhook(
                webhook_id=webhook_id,
                name=body.name,
                url=body.url,
                events=body.events,
                is_active=body.is_active,
            )
            await authority.db.commit()
            return _to_webhook_response(webhook, include_secret=False)
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
    async with tenant_webhook_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=None,
    ) as authority:
        await _require_webhook_tenant_admin(webhook_id, authority)
        deleted = await authority.services.webhooks.delete_webhook(webhook_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Webhook not found"))
        await authority.db.commit()
        return None
