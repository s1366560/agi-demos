"""Unit tests for tenant webhook route authorization."""

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
    list_result: list[Webhook] | None = None
    create_result: Webhook | None = None
    update_result: Webhook | None = None

    async def get_webhook(self, webhook_id: str) -> Webhook | None:
        if self.webhook and self.webhook.id == webhook_id:
            return self.webhook
        return None

    async def list_webhooks(self, _tenant_id: str) -> list[Webhook]:
        return self.list_result or []

    async def create_webhook(self, **_kwargs: object) -> Webhook:
        if not self.create_result:
            raise AssertionError("create_result is required")
        return self.create_result

    async def update_webhook(self, **_kwargs: object) -> Webhook:
        if self.update_result:
            return self.update_result
        raise ValueError("Webhook webhook-secret not found")


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


def _make_webhook(
    *,
    webhook_id: str = "webhook-secret",
    tenant_id: str = "tenant-1",
    secret: str = "whsec_super_secret",
) -> Webhook:
    return Webhook(
        id=webhook_id,
        tenant_id=tenant_id,
        name="Deploy",
        url="https://example.com/hook",
        secret=secret,
        events=["memory.created"],
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


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


@pytest.mark.unit
async def test_update_webhook_sanitizes_not_found_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_admin(*_args: object, **_kwargs: object) -> None:
        return None

    service = FakeWebhookService(None)
    monkeypatch.setattr(tenant_webhooks, "_require_webhook_tenant_admin", allow_admin)
    monkeypatch.setattr(
        tenant_webhooks,
        "get_container_with_db",
        lambda _request, _db: FakeContainer(service),
    )

    with pytest.raises(HTTPException) as exc_info:
        await tenant_webhooks.update_webhook(
            webhook_id="webhook-secret",
            body=tenant_webhooks.WebhookUpdateRequest(
                name="Deploy",
                url="https://example.com/hook",
                events=["memory.created"],
                is_active=True,
            ),
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Webhook not found"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_create_webhook_returns_secret_once(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_admin(*_args: object, **_kwargs: object) -> None:
        return None

    webhook = _make_webhook()
    service = FakeWebhookService(None, create_result=webhook)
    monkeypatch.setattr(tenant_webhooks, "require_tenant_access", allow_admin)
    monkeypatch.setattr(
        tenant_webhooks,
        "get_container_with_db",
        lambda _request, _db: FakeContainer(service),
    )

    response = await tenant_webhooks.create_webhook(
        tenant_id=webhook.tenant_id,
        body=tenant_webhooks.WebhookCreateRequest(
            name=webhook.name,
            url=webhook.url,
            events=webhook.events,
            is_active=webhook.is_active,
        ),
        request=SimpleNamespace(),
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(commit=AsyncMock()),
    )

    assert response.secret == "whsec_super_secret"


@pytest.mark.unit
async def test_list_webhooks_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_admin(*_args: object, **_kwargs: object) -> None:
        return None

    webhook = _make_webhook()
    service = FakeWebhookService(None, list_result=[webhook])
    monkeypatch.setattr(tenant_webhooks, "require_tenant_access", allow_admin)
    monkeypatch.setattr(
        tenant_webhooks,
        "get_container_with_db",
        lambda _request, _db: FakeContainer(service),
    )

    response = await tenant_webhooks.list_webhooks(
        tenant_id=webhook.tenant_id,
        request=SimpleNamespace(),
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(),
    )

    assert response[0].secret is None


@pytest.mark.unit
async def test_update_webhook_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_admin(*_args: object, **_kwargs: object) -> None:
        return None

    webhook = _make_webhook()
    service = FakeWebhookService(webhook, update_result=webhook)
    monkeypatch.setattr(tenant_webhooks, "_require_webhook_tenant_admin", allow_admin)
    monkeypatch.setattr(
        tenant_webhooks,
        "get_container_with_db",
        lambda _request, _db: FakeContainer(service),
    )

    response = await tenant_webhooks.update_webhook(
        webhook_id=webhook.id,
        body=tenant_webhooks.WebhookUpdateRequest(
            name=webhook.name,
            url=webhook.url,
            events=webhook.events,
            is_active=webhook.is_active,
        ),
        request=SimpleNamespace(),
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(commit=AsyncMock()),
    )

    assert response.secret is None
