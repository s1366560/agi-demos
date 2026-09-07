from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.smtp_schemas import SmtpConfigCreate, SmtpTestRequest
from src.domain.model.smtp.smtp_config import SmtpConfig
from src.infrastructure.adapters.primary.web.routers import smtp_config as smtp_config_router
from src.infrastructure.adapters.primary.web.smtp_config_application_authority_v2 import (
    SmtpConfigApplicationAuthorityV2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.smtp_config_services import SmtpConfigApplicationServicesV2


class _FailingSmtpService:
    async def test_smtp(self, _tenant_id: str, _recipient_email: str) -> None:
        raise RuntimeError("smtp auth failed for secret-host.internal with password hunter2")


class _MissingSmtpService:
    async def test_smtp(self, _tenant_id: str, _recipient_email: str) -> None:
        raise ValueError("SMTP config smtp-secret not found")


class _CrudSmtpService:
    def __init__(self, config: SmtpConfig) -> None:
        self.config = config
        self.upsert_calls: list[tuple[str, dict[str, object]]] = []
        self.get_calls: list[str] = []
        self.delete_calls: list[str] = []

    async def upsert_config(self, tenant_id: str, **values: object) -> SmtpConfig:
        self.upsert_calls.append((tenant_id, values))
        return self.config

    async def get_config(self, tenant_id: str) -> SmtpConfig:
        self.get_calls.append(tenant_id)
        return self.config

    async def delete_config(self, config_id: str) -> None:
        self.delete_calls.append(config_id)


def _stored_config() -> SmtpConfig:
    return SmtpConfig(
        id="smtp-1",
        tenant_id="tenant-1",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="mailer",
        smtp_password_encrypted=base64.b64encode(b"operation-secret").decode(),
        from_email="mailer@example.com",
        from_name="MemStack",
        use_tls=True,
    )


def _authority(
    service: object,
    *,
    db: object | None = None,
) -> SmtpConfigApplicationAuthorityV2:
    db_value = SimpleNamespace(commit=AsyncMock()) if db is None else db
    return SmtpConfigApplicationAuthorityV2(
        operation=cast(Any, SimpleNamespace()),
        db=cast(AsyncSession, db_value),
        current_user=cast(User, SimpleNamespace(id="user-1")),
        tenant_id="tenant-1",
        services=SmtpConfigApplicationServicesV2(smtp=cast(Any, service)),
    )


@pytest.mark.unit
async def test_smtp_test_sanitizes_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def require_access(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(smtp_config_router, "_require_tenant_access", require_access)
    authority = _authority(_FailingSmtpService())

    with pytest.raises(HTTPException) as exc_info:
        await smtp_config_router.test_smtp_config(
            tenant_id="tenant-1",
            body=SmtpTestRequest(recipient_email="user@example.com"),
            smtp_application=authority,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "SMTP test failed"
    assert "secret-host" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_smtp_test_sanitizes_missing_config_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def require_access(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(smtp_config_router, "_require_tenant_access", require_access)
    authority = _authority(_MissingSmtpService())

    with pytest.raises(HTTPException) as exc_info:
        await smtp_config_router.test_smtp_config(
            tenant_id="tenant-1",
            body=SmtpTestRequest(recipient_email="user@example.com"),
            smtp_application=authority,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "SMTP config not found"
    assert "smtp-secret" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_smtp_upsert_commits_the_authority_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def require_access(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(smtp_config_router, "_require_tenant_access", require_access)
    service = _CrudSmtpService(_stored_config())
    db = SimpleNamespace(commit=AsyncMock())
    authority = _authority(service, db=db)
    body = SmtpConfigCreate(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="mailer",
        smtp_password="operation-secret",
        from_email="mailer@example.com",
        from_name="MemStack",
        use_tls=True,
    )

    response = await smtp_config_router.upsert_smtp_config(
        tenant_id="tenant-1",
        body=body,
        smtp_application=authority,
    )

    assert response.id == "smtp-1"
    assert service.upsert_calls == [
        (
            "tenant-1",
            {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "mailer",
                "smtp_password": "operation-secret",
                "from_email": "mailer@example.com",
                "from_name": "MemStack",
                "use_tls": True,
            },
        )
    ]
    db.commit.assert_awaited_once_with()


@pytest.mark.unit
async def test_smtp_delete_commits_the_authority_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def require_access(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(smtp_config_router, "_require_tenant_access", require_access)
    service = _CrudSmtpService(_stored_config())
    db = SimpleNamespace(commit=AsyncMock())
    authority = _authority(service, db=db)

    await smtp_config_router.delete_smtp_config(
        tenant_id="tenant-1",
        smtp_application=authority,
    )

    assert service.get_calls == ["tenant-1"]
    assert service.delete_calls == ["smtp-1"]
    db.commit.assert_awaited_once_with()
