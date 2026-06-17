"""Unit tests for sandbox token service security behavior."""

import logging

import pytest

from src.infrastructure.security.sandbox_token_service import SandboxTokenService


@pytest.mark.unit
def test_sandbox_token_logs_do_not_disclose_token_values(caplog: pytest.LogCaptureFixture) -> None:
    service = SandboxTokenService(secret_key="test-secret")
    invalid_token = "invalid-sandbox-token-value-with-secret-prefix"

    with caplog.at_level(
        logging.WARNING,
        logger="src.infrastructure.security.sandbox_token_service",
    ):
        result = service.validate_token(invalid_token)

    assert result.valid is False
    assert invalid_token not in caplog.text
    assert invalid_token[:20] not in caplog.text

    caplog.clear()
    access_token = service.generate_token(
        project_id="project-1",
        user_id="user-1",
        tenant_id="tenant-1",
    )
    caplog.clear()

    with caplog.at_level(
        logging.INFO,
        logger="src.infrastructure.security.sandbox_token_service",
    ):
        revoked = service.revoke_token(access_token.token)

    assert revoked is True
    assert access_token.token not in caplog.text
    assert access_token.token[:20] not in caplog.text
