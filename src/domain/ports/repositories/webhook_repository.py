from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.tenant.webhook import Webhook


class WebhookRepository(ABC):
    @abstractmethod
    async def save(self, domain_entity: Webhook) -> Webhook:
        pass

    @abstractmethod
    async def get_by_id(self, webhook_id: str) -> Webhook | None:
        pass

    @abstractmethod
    async def list_by_tenant(self, tenant_id: str) -> list[Webhook]:
        pass

    @abstractmethod
    async def delete_by_id(self, webhook_id: str) -> bool:
        pass
