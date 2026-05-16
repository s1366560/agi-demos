"""Unit tests for tenant webhook route authorization."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.tenant.webhook import Webhook
from src.infrastructure.adapters.primary.web.routers import tenant_webhooks
from src.infrastructure.adapters.primary.web.routers.tenant_webhooks import (
    _require_webhook_tenant_admin,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User


@dataclass
class FakeWebhookService:
    webhook: Webhook | None

    async def get_webhook(self, webhook_id: str) -> Webhook | None:
        if self.webhook and self.webhook.id == webhook_id:
            return self.webhook
        return None


@dataclass
class FakeContainer:
    service: FakeWebhookService

    def webhook_service(self) -> FakeWebhookService:
        return self.service


def _make_request(service: FakeWebhookService) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "app": type("App", (), {"state": type("State", (), {})()})(),
    }
    request = Request(scope)
    return request


@pytest.mark.unit
class TestTenantWebhookAuthorization:
    @pytest.mark.asyncio
    async def test_allows_tenant_owner(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        webhook = Webhook(
            id="webhook-owned",
            tenant_id=test_project_db.tenant_id,
            name="Deploy",
            url="https://example.com/hook",
            events=["memory.created"],
            created_at=datetime.now(UTC),
        )
        service = FakeWebhookService(webhook)
        monkeypatch.setattr(
            tenant_webhooks,
            "get_container_with_db",
            lambda _request, _db: FakeContainer(service),
        )

        await _require_webhook_tenant_admin(
            webhook.id,
            _make_request(service),
            test_user,
            test_db,
        )

    @pytest.mark.asyncio
    async def test_rejects_non_member(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        webhook = Webhook(
            id="webhook-other-user",
            tenant_id=test_project_db.tenant_id,
            name="Deploy",
            url="https://example.com/hook",
            events=["memory.created"],
            created_at=datetime.now(UTC),
        )
        service = FakeWebhookService(webhook)
        monkeypatch.setattr(
            tenant_webhooks,
            "get_container_with_db",
            lambda _request, _db: FakeContainer(service),
        )

        with pytest.raises(HTTPException) as exc_info:
            await _require_webhook_tenant_admin(
                webhook.id,
                _make_request(service),
                another_user,
                test_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_missing_webhook_returns_404(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        service = FakeWebhookService(None)
        monkeypatch.setattr(
            tenant_webhooks,
            "get_container_with_db",
            lambda _request, _db: FakeContainer(service),
        )

        with pytest.raises(HTTPException) as exc_info:
            await _require_webhook_tenant_admin(
                "missing-webhook",
                _make_request(service),
                test_user,
                test_db,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
