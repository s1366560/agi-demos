"""Unit tests for sandbox token routes."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.configuration.config import get_settings
from src.infrastructure.adapters.primary.web.routers.sandbox import (
    tokens as tokens_router,
    utils as sandbox_utils,
)
from src.infrastructure.security.sandbox_token_service import SandboxTokenService


@pytest.fixture
def sandbox_token_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, SandboxTokenService]:
    """Create a token-route client with a deterministic service credential."""
    token_service = SandboxTokenService(secret_key="test-secret")
    app = FastAPI()
    app.include_router(tokens_router.router, prefix="/api/v1/sandbox")
    app.dependency_overrides[tokens_router.get_sandbox_token_service] = lambda: token_service
    app.dependency_overrides[tokens_router.get_current_user] = lambda: SimpleNamespace(
        id="user-1",
        is_superuser=True,
        tenants=[SimpleNamespace(tenant_id="tenant-1")],
    )
    app.dependency_overrides[tokens_router.get_db] = lambda: None
    monkeypatch.setattr(
        tokens_router,
        "get_settings",
        lambda: SimpleNamespace(sandbox_service_token="service-secret"),
    )
    return TestClient(app), token_service


@pytest.mark.unit
def test_validate_token_requires_service_bearer(
    sandbox_token_client: tuple[TestClient, SandboxTokenService],
) -> None:
    client, token_service = sandbox_token_client
    access_token = token_service.generate_token(
        project_id="project-1",
        user_id="user-1",
        tenant_id="tenant-1",
        sandbox_type="local",
    )

    response = client.post(
        "/api/v1/sandbox/token/validate",
        json={"token": access_token.token, "project_id": "project-1"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.unit
def test_validate_token_accepts_service_bearer_and_omits_user_id(
    sandbox_token_client: tuple[TestClient, SandboxTokenService],
) -> None:
    client, token_service = sandbox_token_client
    access_token = token_service.generate_token(
        project_id="project-1",
        user_id="user-1",
        tenant_id="tenant-1",
        sandbox_type="local",
    )

    response = client.post(
        "/api/v1/sandbox/token/validate",
        headers={"Authorization": "Bearer service-secret"},
        json={"token": access_token.token, "project_id": "project-1"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "valid": True,
        "project_id": "project-1",
        "user_id": None,
        "sandbox_type": "local",
        "error": None,
    }


@pytest.mark.unit
def test_validate_token_fails_closed_when_service_token_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(tokens_router.router, prefix="/api/v1/sandbox")
    monkeypatch.setattr(
        tokens_router,
        "get_settings",
        lambda: SimpleNamespace(sandbox_service_token=None),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/sandbox/token/validate",
        headers={"Authorization": "Bearer service-secret"},
        json={"token": "sandbox-token"},
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.unit
def test_generate_sandbox_token_does_not_put_token_in_websocket_hint(
    sandbox_token_client: tuple[TestClient, SandboxTokenService],
) -> None:
    client, _token_service = sandbox_token_client

    response = client.post(
        "/api/v1/sandbox/projects/project-1/token",
        json={"sandbox_type": "local", "ttl_seconds": 300},
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["token"]
    assert payload["websocket_url_hint"] == "wss://your-tunnel-url"
    assert payload["token"] not in payload["websocket_url_hint"]
    assert "token=" not in payload["websocket_url_hint"]


@pytest.mark.unit
def test_sandbox_token_service_uses_configured_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    get_settings.cache_clear()
    sandbox_utils._sandbox_token_service = None

    try:
        token_service = sandbox_utils.get_sandbox_token_service()
        access_token = token_service.generate_token(
            project_id="project-1",
            user_id="user-1",
            tenant_id="tenant-1",
        )
    finally:
        sandbox_utils._sandbox_token_service = None
        get_settings.cache_clear()

    assert token_service.validate_token(access_token.token).valid is True
