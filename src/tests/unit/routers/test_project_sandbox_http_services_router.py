"""Unit tests for project sandbox HTTP service routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.routers import project_sandbox as router_mod


@pytest.fixture
def sandbox_http_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a TestClient with lightweight dependency overrides."""
    app = FastAPI()
    app.include_router(router_mod.router)

    router_mod._http_service_registry.clear()

    async def _allow_access(*args, **kwargs) -> None:
        return None

    async def _current_user():
        return SimpleNamespace(id="user-1")

    async def _tenant_id() -> str:
        return "tenant-1"

    async def _db():
        yield Mock()

    lifecycle_service = AsyncMock()
    lifecycle_service.ensure_sandbox_running = AsyncMock(
        return_value=SimpleNamespace(sandbox_id="sandbox-1")
    )

    app.dependency_overrides[router_mod.get_current_user] = _current_user
    app.dependency_overrides[router_mod.get_current_user_from_desktop_proxy] = _current_user
    app.dependency_overrides[router_mod.get_current_user_from_header_or_query] = _current_user
    app.dependency_overrides[router_mod.get_current_user_tenant] = _tenant_id
    app.dependency_overrides[router_mod.get_db] = _db
    app.dependency_overrides[router_mod.get_lifecycle_service] = lambda: lifecycle_service
    app.dependency_overrides[router_mod.get_sandbox_adapter] = lambda: SimpleNamespace(_docker=None)
    app.dependency_overrides[router_mod.get_event_publisher] = lambda: None

    manager = AsyncMock()
    manager.broadcast_sandbox_state = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: manager,
    )
    monkeypatch.setattr(router_mod, "verify_project_access", _allow_access)

    return TestClient(app)


@pytest.mark.unit
def test_register_list_stop_external_http_service(sandbox_http_client: TestClient) -> None:
    """Register/list/stop flow should work for external_url services."""
    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "name": "docs",
            "source_type": "external_url",
            "external_url": "https://example.com/docs",
            "auto_open": True,
        },
    )
    assert response.status_code == status.HTTP_200_OK
    service_id = response.json()["service_id"]

    list_response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/http-services")
    assert list_response.status_code == status.HTTP_200_OK
    assert list_response.json()["total"] == 1

    stop_response = sandbox_http_client.delete(
        f"/api/v1/projects/proj-1/sandbox/http-services/{service_id}"
    )
    assert stop_response.status_code == status.HTTP_200_OK
    assert stop_response.json()["service"]["status"] == "stopped"


@pytest.mark.unit
def test_register_internal_requires_internal_port(sandbox_http_client: TestClient) -> None:
    """sandbox_internal source_type must provide internal_port."""
    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "name": "vite",
            "source_type": "sandbox_internal",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "internal_port is required" in response.json()["detail"]


@pytest.mark.unit
def test_stop_http_service_not_found(sandbox_http_client: TestClient) -> None:
    """Deleting a missing service returns 404."""
    response = sandbox_http_client.delete("/api/v1/projects/proj-1/sandbox/http-services/missing")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
def test_http_proxy_rejects_external_service_source(sandbox_http_client: TestClient) -> None:
    """HTTP reverse proxy endpoint is only valid for sandbox_internal services."""
    register = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "service_id": "svc-ext",
            "name": "external",
            "source_type": "external_url",
            "external_url": "https://example.com",
        },
    )
    assert register.status_code == status.HTTP_200_OK

    response = sandbox_http_client.get(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-ext/proxy/"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "only available for sandbox_internal services" in response.json()["detail"]


@pytest.mark.unit
def test_http_proxy_returns_404_when_service_missing(sandbox_http_client: TestClient) -> None:
    """HTTP reverse proxy endpoint returns 404 for unknown service."""
    response = sandbox_http_client.get(
        "/api/v1/projects/proj-1/sandbox/http-services/nope/proxy/"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
def test_http_proxy_returns_502_when_upstream_fails(
    sandbox_http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTTP reverse proxy should map upstream connection errors to 502."""
    router_mod._http_service_registry.setdefault("proj-1", {})["svc-int"] = router_mod.HttpServiceProxyInfo(
        service_id="svc-int",
        name="internal",
        source_type=router_mod.HttpServiceSourceType.SANDBOX_INTERNAL,
        status="running",
        service_url="http://127.0.0.1:3000",
        preview_url="/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/",
        ws_preview_url="/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/ws/",
        sandbox_id="sandbox-1",
        auto_open=True,
        restart_token="r1",
        updated_at="2025-01-01T00:00:00+00:00",
    )

    class _FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, *args, **kwargs):
            req = httpx.Request("GET", "http://127.0.0.1:3000")
            raise httpx.RequestError("connection refused", request=req)

    monkeypatch.setattr("httpx.AsyncClient", _FailingAsyncClient)

    response = sandbox_http_client.get(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/"
    )
    assert response.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.unit
def test_http_proxy_rewrites_root_relative_assets(
    sandbox_http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTML content from upstream should be rewritten to use proxy paths."""
    router_mod._http_service_registry.setdefault("proj-1", {})["svc-int"] = router_mod.HttpServiceProxyInfo(
        service_id="svc-int",
        name="internal",
        source_type=router_mod.HttpServiceSourceType.SANDBOX_INTERNAL,
        status="running",
        service_url="http://127.0.0.1:3000",
        preview_url="/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/",
        ws_preview_url="/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/ws/",
        sandbox_id="sandbox-1",
        auto_open=True,
        restart_token="r1",
        updated_at="2025-01-01T00:00:00+00:00",
    )

    class _SuccessAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, *args, **kwargs):
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/html"},
                content=b'<html><script src="/main.js"></script></html>',
            )

    monkeypatch.setattr("httpx.AsyncClient", _SuccessAsyncClient)

    response = sandbox_http_client.get(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/?token=ms_sk_test",
    )
    assert response.status_code == status.HTTP_200_OK
    assert "/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/main.js?token=ms_sk_test" in (
        response.text
    )
