"""Unit tests for project sandbox HTTP service routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse

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
    app.include_router(router_mod.preview_router)

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
def test_http_services_list_and_proxy_load_from_redis_when_memory_empty(
    sandbox_http_client: TestClient,
) -> None:
    """List/proxy routes should recover service records from Redis when memory cache is empty."""

    class _FakeRedisClient:
        def __init__(self) -> None:
            self._hashes: dict[str, dict[str, str]] = {}

        async def hget(self, key: str, field: str) -> str | None:
            return self._hashes.get(key, {}).get(field)

        async def hset(self, key: str, field: str, value: str) -> None:
            self._hashes.setdefault(key, {})[field] = value

        async def hgetall(self, key: str) -> dict[str, str]:
            return self._hashes.get(key, {}).copy()

    fake_redis = _FakeRedisClient()
    sandbox_http_client.app.dependency_overrides[router_mod.get_http_service_redis_client] = (
        lambda: fake_redis
    )

    register_response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "service_id": "svc-redis",
            "name": "docs",
            "source_type": "external_url",
            "external_url": "https://example.com/docs",
        },
    )
    assert register_response.status_code == status.HTTP_200_OK

    router_mod._http_service_registry.clear()

    list_response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/http-services")
    assert list_response.status_code == status.HTTP_200_OK
    assert list_response.json()["total"] == 1
    assert list_response.json()["services"][0]["service_id"] == "svc-redis"

    router_mod._http_service_registry.clear()

    proxy_response = sandbox_http_client.get(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-redis/proxy/"
    )
    assert proxy_response.status_code == status.HTTP_400_BAD_REQUEST
    assert "only available for sandbox_internal services" in proxy_response.json()["detail"]


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
def test_register_http_service_emits_error_event_on_registration_failure(
    sandbox_http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registration failures should emit http_service_error once service_id is known."""
    event_publisher = AsyncMock()
    event_publisher.publish_http_service_error = AsyncMock()
    sandbox_http_client.app.dependency_overrides[router_mod.get_event_publisher] = (
        lambda: event_publisher
    )

    async def _raise_on_upsert(*args, **kwargs) -> tuple[bool, router_mod.HttpServiceProxyInfo]:
        raise RuntimeError("persist failed")

    monkeypatch.setattr(router_mod, "_upsert_http_service", _raise_on_upsert)

    # Assert API contract (500 response) instead of framework exception bubbling.
    with TestClient(sandbox_http_client.app, raise_server_exceptions=False) as api_client:
        response = api_client.post(
            "/api/v1/projects/proj-1/sandbox/http-services",
            json={
                "service_id": "svc-fail",
                "name": "docs",
                "source_type": "external_url",
                "external_url": "https://example.com/docs",
            },
        )
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    event_publisher.publish_http_service_error.assert_awaited_once()
    error_kwargs = event_publisher.publish_http_service_error.await_args.kwargs
    assert error_kwargs["project_id"] == "proj-1"
    assert error_kwargs["service_id"] == "svc-fail"
    assert error_kwargs["service_name"] == "docs"
    assert error_kwargs["error_message"] == "persist failed"


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
    response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/http-services/nope/proxy/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
def test_http_proxy_returns_502_when_upstream_fails(
    sandbox_http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTTP reverse proxy should map upstream connection errors to 502."""
    event_publisher = AsyncMock()
    event_publisher.publish_http_service_error = AsyncMock()
    sandbox_http_client.app.dependency_overrides[router_mod.get_event_publisher] = (
        lambda: event_publisher
    )

    router_mod._http_service_registry.setdefault("proj-1", {})["svc-int"] = (
        router_mod.HttpServiceProxyInfo(
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

    async def _raise_exec_fetch(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(router_mod, "_request_http_service_via_sandbox_exec", _raise_exec_fetch)

    response = sandbox_http_client.get(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/"
    )
    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    event_publisher.publish_http_service_error.assert_awaited_once()
    error_kwargs = event_publisher.publish_http_service_error.await_args.kwargs
    assert error_kwargs["project_id"] == "proj-1"
    assert error_kwargs["service_id"] == "svc-int"
    assert error_kwargs["service_name"] == "internal"
    assert "connection refused" in error_kwargs["error_message"]


@pytest.mark.unit
def test_http_proxy_rewrites_root_relative_assets(
    sandbox_http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTML content from upstream should be rewritten to use proxy paths."""
    router_mod._http_service_registry.setdefault("proj-1", {})["svc-int"] = (
        router_mod.HttpServiceProxyInfo(
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
    assert (
        "/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/main.js?token=ms_sk_test"
        in (response.text)
    )


@pytest.mark.unit
def test_create_preview_session_returns_host_based_launch_url(
    sandbox_http_client: TestClient,
) -> None:
    """Preview launch URL should use a root host instead of a path-prefixed proxy."""
    router_mod._http_service_registry.setdefault("proj-1", {})["svc-int"] = (
        router_mod.HttpServiceProxyInfo(
            service_id="svc-int",
            name="internal",
            source_type=router_mod.HttpServiceSourceType.SANDBOX_INTERNAL,
            status="running",
            service_url="http://127.0.0.1:3000",
            preview_url=router_mod._build_http_preview_proxy_url("proj-1", "svc-int"),
            ws_preview_url=router_mod._build_http_preview_ws_proxy_url("proj-1", "svc-int"),
            sandbox_id="sandbox-1",
            auto_open=True,
            restart_token="r1",
            updated_at="2025-01-01T00:00:00+00:00",
        )
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-int/preview-session"
    )

    assert response.status_code == status.HTTP_200_OK
    parsed = urlparse(response.json()["preview_url"])
    assert parsed.hostname == "svc-int.proj-1.preview.localhost"
    assert parsed.path == "/"
    assert router_mod._PREVIEW_SESSION_QUERY_PARAM in parse_qs(parsed.query)


@pytest.mark.unit
def test_host_preview_proxy_redirects_session_token_to_clean_url(
    sandbox_http_client: TestClient,
) -> None:
    """One-time preview launch token should be moved into a host cookie."""
    token = router_mod._create_preview_session_token("proj-1", "svc-int", "user-1")
    router_mod._http_service_registry.setdefault("proj-1", {})["svc-int"] = (
        router_mod.HttpServiceProxyInfo(
            service_id="svc-int",
            name="internal",
            source_type=router_mod.HttpServiceSourceType.SANDBOX_INTERNAL,
            status="running",
            service_url="http://127.0.0.1:3000",
            preview_url=router_mod._build_http_preview_proxy_url("proj-1", "svc-int"),
            ws_preview_url=router_mod._build_http_preview_ws_proxy_url("proj-1", "svc-int"),
            sandbox_id="sandbox-1",
            auto_open=True,
            restart_token="r1",
            updated_at="2025-01-01T00:00:00+00:00",
        )
    )

    response = sandbox_http_client.get(
        f"/?{router_mod._PREVIEW_SESSION_QUERY_PARAM}={token}",
        headers={"host": "svc-int.proj-1.preview.localhost:8000"},
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_302_FOUND
    assert response.headers["location"] == "http://svc-int.proj-1.preview.localhost:8000/"
    assert router_mod._PREVIEW_SESSION_COOKIE_NAME in response.headers["set-cookie"]


@pytest.mark.unit
def test_host_preview_proxy_keeps_root_relative_assets_unmodified(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host-based preview should preserve normal root-relative app URLs."""
    token = router_mod._create_preview_session_token("proj-1", "svc-int", "user-1")
    router_mod._http_service_registry.setdefault("proj-1", {})["svc-int"] = (
        router_mod.HttpServiceProxyInfo(
            service_id="svc-int",
            name="internal",
            source_type=router_mod.HttpServiceSourceType.SANDBOX_INTERNAL,
            status="running",
            service_url="http://127.0.0.1:3000",
            preview_url=router_mod._build_http_preview_proxy_url("proj-1", "svc-int"),
            ws_preview_url=router_mod._build_http_preview_ws_proxy_url("proj-1", "svc-int"),
            sandbox_id="sandbox-1",
            auto_open=True,
            restart_token="r1",
            updated_at="2025-01-01T00:00:00+00:00",
        )
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
        "/",
        headers={"host": "svc-int.proj-1.preview.localhost:8000"},
        cookies={router_mod._PREVIEW_SESSION_COOKIE_NAME: token},
    )

    assert response.status_code == status.HTTP_200_OK
    assert '<script src="/main.js">' in response.text
    assert "/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/main.js" not in (
        response.text
    )
