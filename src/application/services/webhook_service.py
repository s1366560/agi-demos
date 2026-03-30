from __future__ import annotations

import logging
import secrets

from src.domain.model.tenant.webhook import Webhook
from src.domain.ports.repositories.webhook_repository import WebhookRepository

logger = logging.getLogger(__name__)


class WebhookService:
    def __init__(self, webhook_repo: WebhookRepository) -> None:
        self._webhook_repo = webhook_repo

    async def create_webhook(
        self,
        tenant_id: str,
        name: str,
        url: str,
        events: list[str],
        is_active: bool = True,
    ) -> Webhook:
        secret = f"whsec_{secrets.token_hex(32)}"

        webhook = Webhook(
            tenant_id=tenant_id,
            name=name,
            url=url,
            secret=secret,
            events=events,
            is_active=is_active,
        )
        await self._webhook_repo.save(webhook)
        logger.info(f"Created webhook {webhook.id} for tenant {tenant_id}")
        return webhook

    async def get_webhook(self, webhook_id: str) -> Webhook | None:
        return await self._webhook_repo.get_by_id(webhook_id)

    async def list_webhooks(self, tenant_id: str) -> list[Webhook]:
        return await self._webhook_repo.list_by_tenant(tenant_id)

    async def update_webhook(
        self,
        webhook_id: str,
        name: str,
        url: str,
        events: list[str],
        is_active: bool,
    ) -> Webhook:
        webhook = await self._webhook_repo.get_by_id(webhook_id)
        if not webhook:
            raise ValueError(f"Webhook {webhook_id} not found")

        webhook.update(
            name=name,
            url=url,
            secret=webhook.secret,
            events=events,
            is_active=is_active,
        )
        await self._webhook_repo.save(webhook)
        logger.info(f"Updated webhook {webhook.id}")
        return webhook

    async def delete_webhook(self, webhook_id: str) -> bool:
        deleted = await self._webhook_repo.delete_by_id(webhook_id)
        if deleted:
            logger.info(f"Deleted webhook {webhook_id}")
        return deleted
