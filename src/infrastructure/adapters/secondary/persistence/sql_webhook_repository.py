from __future__ import annotations

import uuid
from typing import override

from sqlalchemy import select

from src.domain.model.tenant.webhook import Webhook
from src.domain.ports.repositories.webhook_repository import WebhookRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import WebhookModel


class SqlWebhookRepository(BaseRepository[Webhook, WebhookModel], WebhookRepository):
    _model_class = WebhookModel

    @override
    def _to_domain(self, db_model: WebhookModel | None) -> Webhook | None:
        if db_model is None:
            return None
        return Webhook(
            id=db_model.id,
            tenant_id=db_model.tenant_id,
            name=db_model.name,
            url=db_model.url,
            secret=db_model.secret,
            events=db_model.events if db_model.events else [],
            is_active=db_model.is_active,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: Webhook) -> WebhookModel:
        return WebhookModel(
            id=domain_entity.id or str(uuid.uuid4()),
            tenant_id=domain_entity.tenant_id,
            name=domain_entity.name,
            url=domain_entity.url,
            secret=domain_entity.secret,
            events=domain_entity.events,
            is_active=domain_entity.is_active,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    async def get_by_id(self, webhook_id: str) -> Webhook | None:
        return await self.find_by_id(webhook_id)

    @override
    async def list_by_tenant(self, tenant_id: str) -> list[Webhook]:
        stmt = (
            select(WebhookModel)
            .where(WebhookModel.tenant_id == tenant_id, WebhookModel.deleted_at.is_(None))
            .order_by(WebhookModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [d for row in result.scalars().all() if (d := self._to_domain(row)) is not None]

    @override
    async def delete_by_id(self, webhook_id: str) -> bool:
        # Override to do soft delete
        stmt = select(WebhookModel).where(
            WebhookModel.id == webhook_id, WebhookModel.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        db_model = result.scalar_one_or_none()
        if not db_model:
            return False

        # Soft delete logic
        from datetime import UTC, datetime

        db_model.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return True
