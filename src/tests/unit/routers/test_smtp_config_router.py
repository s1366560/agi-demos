from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from src.application.schemas.smtp_schemas import SmtpTestRequest
from src.infrastructure.adapters.primary.web.routers import smtp_config as smtp_config_router


class _FailingSmtpService:
    async def test_smtp(self, _tenant_id: str, _recipient_email: str) -> None:
        raise RuntimeError("smtp auth failed for secret-host.internal with password hunter2")


class _MissingSmtpService:
    async def test_smtp(self, _tenant_id: str, _recipient_email: str) -> None:
        raise ValueError("SMTP config smtp-secret not found")


@pytest.mark.unit
async def test_smtp_test_sanitizes_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def require_access(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(smtp_config_router, "_require_tenant_access", require_access)
    monkeypatch.setattr(smtp_config_router, "_build_service", lambda _db: _FailingSmtpService())

    with pytest.raises(HTTPException) as exc_info:
        await smtp_config_router.test_smtp_config(
            tenant_id="tenant-1",
            body=SmtpTestRequest(recipient_email="user@example.com"),
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "SMTP test failed"
    assert "secret-host" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_smtp_test_sanitizes_missing_config_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def require_access(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(smtp_config_router, "_require_tenant_access", require_access)
    monkeypatch.setattr(smtp_config_router, "_build_service", lambda _db: _MissingSmtpService())

    with pytest.raises(HTTPException) as exc_info:
        await smtp_config_router.test_smtp_config(
            tenant_id="tenant-1",
            body=SmtpTestRequest(recipient_email="user@example.com"),
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "SMTP config not found"
    assert "smtp-secret" not in str(exc_info.value.detail)
