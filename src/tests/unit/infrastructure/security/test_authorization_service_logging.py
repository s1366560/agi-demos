"""Logging tests for infrastructure authorization service."""

import logging
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.security.authorization_service import AuthorizationService


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuthorizationServiceLogging:
    """Verify authorization fallback logs do not expose scoped identifiers."""

    async def test_check_permission_error_log_redacts_user_and_exception_content(
        self,
        caplog,
    ) -> None:
        secret_user_id = "user-auth-secret"
        exception_detail = "permission backend leaked user user-auth-secret"
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError(exception_detail))
        service = AuthorizationService(session)
        caplog.set_level(logging.ERROR, logger="src.infrastructure.security.authorization_service")

        allowed = await service.check_permission(
            user_id=secret_user_id,
            permission="project:read",
            tenant_id="tenant-auth-secret",
            project_id="project-auth-secret",
        )

        assert allowed is False
        assert secret_user_id not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    async def test_get_user_permissions_error_log_redacts_user_and_exception_content(
        self,
        caplog,
    ) -> None:
        secret_user_id = "user-permissions-secret"
        exception_detail = "permissions backend leaked user user-permissions-secret"
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError(exception_detail))
        service = AuthorizationService(session)
        caplog.set_level(logging.ERROR, logger="src.infrastructure.security.authorization_service")

        permissions = await service.get_user_permissions(
            user_id=secret_user_id,
            tenant_id="tenant-permissions-secret",
            project_id="project-permissions-secret",
        )

        assert permissions == []
        assert secret_user_id not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
