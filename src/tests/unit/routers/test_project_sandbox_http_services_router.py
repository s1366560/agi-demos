"""Unit tests for project sandbox HTTP service routes."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import websockets
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.routers import project_sandbox as router_mod


@pytest.fixture(autouse=True)
def allow_project_access_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep focused route tests on their target behavior unless they override access."""

    async def _allow_access(*_args, **_kwargs) -> str:
        return "tenant-1"

    monkeypatch.setattr(router_mod, "verify_project_access", _allow_access)


@pytest.fixture
def sandbox_http_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a TestClient with lightweight dependency overrides."""
    app = FastAPI()
    app.include_router(router_mod.router)
    app.include_router(router_mod.preview_router)

    router_mod._http_service_registry.clear()

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
    orchestrator = SimpleNamespace(
        stop_desktop=AsyncMock(return_value=True),
        stop_terminal=AsyncMock(return_value=True),
    )

    app.dependency_overrides[router_mod.get_current_user] = _current_user
    app.dependency_overrides[router_mod.get_current_user_from_desktop_proxy] = _current_user
    app.dependency_overrides[router_mod.get_current_user_tenant] = _tenant_id
    app.dependency_overrides[router_mod.get_db] = _db
    app.dependency_overrides[router_mod.get_lifecycle_service] = lambda: lifecycle_service
    app.dependency_overrides[router_mod.get_sandbox_adapter] = lambda: SimpleNamespace(_docker=None)
    app.dependency_overrides[router_mod.get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[router_mod.get_event_publisher] = lambda: None

    manager = AsyncMock()
    manager.broadcast_sandbox_state = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: manager,
    )
    return TestClient(app)


class _FakeWebSocket:
    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        query_items: list[tuple[str, str]] | None = None,
    ) -> None:
        self.accepted = False
        self.accepted_subprotocol: str | None = None
        self.sent_json: list[object] = []
        self.sent_text: list[str] = []
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.headers = headers or {}
        self.cookies = cookies or {}
        items = query_items or []
        query_map = dict(items)
        self.query_params = SimpleNamespace(
            multi_items=lambda: items,
            get=lambda key, default=None: query_map.get(key, default),
        )

    async def accept(self, *args, **kwargs) -> None:
        self.accepted = True
        self.accepted_subprotocol = kwargs.get("subprotocol")

    async def send_json(self, data: object) -> None:
        self.sent_json.append(data)

    async def send_text(self, data: str) -> None:
        self.sent_text.append(data)

    async def close(self, *args, **kwargs) -> None:
        self.close_code = kwargs.get("code", args[0] if args else None)
        self.close_reason = kwargs.get("reason")
        self.closed = True


class _SandboxService:
    def __init__(self, **sandbox_info: object) -> None:
        self._sandbox_info = SimpleNamespace(sandbox_id="sandbox-1", **sandbox_info)

    async def get_project_sandbox(self, _project_id: str) -> SimpleNamespace:
        return self._sandbox_info


class _FailingEventPublisherContainer:
    def sandbox_event_publisher(self) -> object:
        raise RuntimeError("event publisher secret")


class _FailingRedisClientContainer:
    @property
    def redis_client(self) -> object:
        raise RuntimeError("redis client secret")


class _FailingSandboxLifecycleEventPublisher:
    async def publish_sandbox_created(self, **_kwargs: object) -> None:
        raise RuntimeError("sandbox created secret for proj-1")

    async def publish_sandbox_status(self, **_kwargs: object) -> None:
        raise RuntimeError("sandbox restarted secret for proj-1")

    async def publish_sandbox_terminated(self, **_kwargs: object) -> None:
        raise RuntimeError("sandbox terminated secret for proj-1")


class _FailingSandboxStateBroadcastManager:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    async def broadcast_sandbox_state(self, **_kwargs: object) -> None:
        raise RuntimeError(self.secret)


class _FailingHttpServiceStoppedPublisher:
    async def publish_http_service_stopped(self, **_kwargs: object) -> None:
        raise RuntimeError("http service stopped secret for svc-secret")


class _FailingHttpServiceErrorPublisher:
    async def publish_http_service_error(self, **_kwargs: object) -> None:
        raise RuntimeError("http service error secret for svc-secret")


class _FailingHttpServiceStartedPublisher:
    async def publish_http_service_started(self, **_kwargs: object) -> None:
        raise RuntimeError("http service started secret for svc-secret")


def _sandbox_info(project_id: str = "proj-1") -> router_mod.SandboxInfo:
    return router_mod.SandboxInfo(
        sandbox_id="sandbox-1",
        project_id=project_id,
        tenant_id="tenant-project",
        status="running",
    )


@pytest.mark.unit
def test_get_event_publisher_error_log_omits_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=_FailingEventPublisherContainer()))
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    result = router_mod.get_event_publisher(request)

    assert result is None
    assert "Could not create event publisher" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "event publisher secret" not in caplog.text


@pytest.mark.unit
def test_get_event_publisher_for_websocket_error_log_omits_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    websocket = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=_FailingEventPublisherContainer()))
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    result = router_mod.get_event_publisher_for_websocket(websocket)

    assert result is None
    assert "Could not create websocket event publisher" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "event publisher secret" not in caplog.text


@pytest.mark.unit
def test_get_http_service_redis_client_error_log_omits_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=_FailingRedisClientContainer()))
    )
    caplog.set_level(
        logging.DEBUG,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    result = router_mod.get_http_service_redis_client(request)

    assert result is None
    assert "Could not get Redis client for HTTP service routes" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "redis client secret" not in caplog.text


@pytest.mark.unit
def test_get_http_service_redis_client_for_websocket_error_log_omits_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    websocket = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=_FailingRedisClientContainer()))
    )
    caplog.set_level(
        logging.DEBUG,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    result = router_mod.get_http_service_redis_client_for_websocket(websocket)

    assert result is None
    assert "Could not get Redis client for HTTP service websocket routes" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "redis client secret" not in caplog.text


@pytest.mark.unit
async def test_resolve_sandbox_container_ip_error_log_omits_ids_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Container IP lookup failures should not leak sandbox IDs or Docker errors."""

    class _FailingContainers:
        def get(self, _sandbox_id):
            raise RuntimeError("docker secret for sandbox-secret")

    adapter = SimpleNamespace(_docker=SimpleNamespace(containers=_FailingContainers()))
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_mod._resolve_sandbox_container_ip(adapter, "sandbox-secret")

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == "Unable to resolve sandbox network address"
    assert "Failed to resolve sandbox container IP" in caplog.text
    assert "has_sandbox_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "sandbox-secret" not in caplog.text
    assert "docker secret" not in caplog.text


@pytest.mark.unit
async def test_publish_http_service_error_event_log_omits_ids_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failed http_service_error publishing should not leak service IDs or publisher errors."""
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    await router_mod._publish_http_service_error_event(
        _FailingHttpServiceErrorPublisher(),
        project_id="proj-1",
        sandbox_id="sandbox-secret",
        service_id="svc-secret",
        service_name="secret service",
        error_message="RuntimeError",
    )

    assert "Failed to publish http_service_error" in caplog.text
    assert "has_service_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "svc-secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text
    assert "http service error secret" not in caplog.text


@pytest.mark.unit
def test_ensure_project_sandbox_publish_error_log_omits_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.get_or_create_sandbox = AsyncMock(return_value=_sandbox_info())
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_event_publisher] = (
        lambda: _FailingSandboxLifecycleEventPublisher()
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox",
        json={"profile": "standard"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to publish sandbox_created event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "sandbox created secret" not in caplog.text
    assert "proj-1" not in caplog.text


@pytest.mark.unit
def test_ensure_project_sandbox_broadcast_error_log_omits_exception_text(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.get_or_create_sandbox = AsyncMock(return_value=_sandbox_info())
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: _FailingSandboxStateBroadcastManager("broadcast created secret for proj-1"),
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox",
        json={"profile": "standard"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to broadcast sandbox state via WebSocket" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "broadcast created secret" not in caplog.text
    assert "proj-1" not in caplog.text


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
def test_register_http_service_publish_error_log_omits_ids_and_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HTTP service start event failures should not leak service IDs or publisher errors."""
    sandbox_http_client.app.dependency_overrides[router_mod.get_event_publisher] = (
        lambda: _FailingHttpServiceStartedPublisher()
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "service_id": "svc-secret",
            "name": "Docs",
            "source_type": "external_url",
            "external_url": "https://example.com/docs",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to publish http_service_started event" in caplog.text
    assert "has_service_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "http service started secret" not in caplog.text
    assert "svc-secret" not in caplog.text


@pytest.mark.unit
def test_register_http_service_broadcast_error_log_omits_ids_and_exception_text(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HTTP service start broadcasts should not leak service IDs or publisher errors."""
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: _FailingSandboxStateBroadcastManager("broadcast started secret for svc-secret"),
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "service_id": "svc-secret",
            "name": "Docs",
            "source_type": "external_url",
            "external_url": "https://example.com/docs",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to broadcast http_service_started websocket state" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "broadcast started secret" not in caplog.text
    assert "svc-secret" not in caplog.text


@pytest.mark.unit
def test_stop_http_service_publish_error_log_omits_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    create_response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "service_id": "svc-secret",
            "name": "Docs",
            "source_type": "external_url",
            "external_url": "https://example.com/docs",
        },
    )
    assert create_response.status_code == status.HTTP_200_OK

    sandbox_http_client.app.dependency_overrides[router_mod.get_event_publisher] = (
        lambda: _FailingHttpServiceStoppedPublisher()
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.delete(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-secret"
    )

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to publish http_service_stopped" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "http service stopped secret" not in caplog.text
    assert "svc-secret" not in caplog.text


@pytest.mark.unit
def test_stop_http_service_broadcast_error_log_omits_exception_text(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    create_response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "service_id": "svc-secret",
            "name": "Docs",
            "source_type": "external_url",
            "external_url": "https://example.com/docs",
        },
    )
    assert create_response.status_code == status.HTTP_200_OK

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: _FailingSandboxStateBroadcastManager("http service broadcast secret for svc-secret"),
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.delete(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-secret"
    )

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to broadcast http_service_stopped websocket state" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "http service broadcast secret" not in caplog.text
    assert "svc-secret" not in caplog.text


@pytest.mark.unit
def test_ensure_project_sandbox_sanitizes_internal_errors(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sandbox lifecycle failures should not leak backend exception details."""
    lifecycle_service = AsyncMock()
    lifecycle_service.get_or_create_sandbox = AsyncMock(
        side_effect=RuntimeError("docker://secret-host/sandbox-create")
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox",
        json={"profile": "standard"},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Failed to create sandbox"
    assert "secret-host" not in response.text
    assert "Failed to ensure sandbox" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "proj-1" not in caplog.text
    assert "secret-host" not in caplog.text


@pytest.mark.unit
def test_ensure_project_sandbox_uses_project_tenant_from_access_check(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sandbox creation must use the accessed project's tenant, not the user's active tenant."""

    async def allow_access(*_args, **_kwargs) -> str:
        return "tenant-project"

    monkeypatch.setattr(router_mod, "verify_project_access", allow_access)

    lifecycle_service = AsyncMock()
    lifecycle_service.get_or_create_sandbox = AsyncMock(
        return_value=router_mod.SandboxInfo(
            sandbox_id="sandbox-1",
            project_id="proj-1",
            tenant_id="tenant-project",
            status="running",
        )
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    manager = AsyncMock()
    manager.broadcast_sandbox_state = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: manager,
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox",
        json={"profile": "standard"},
    )

    assert response.status_code == status.HTTP_200_OK
    lifecycle_service.get_or_create_sandbox.assert_awaited_once()
    assert lifecycle_service.get_or_create_sandbox.await_args.kwargs["tenant_id"] == (
        "tenant-project"
    )
    manager.broadcast_sandbox_state.assert_awaited_once()
    assert manager.broadcast_sandbox_state.await_args.kwargs["tenant_id"] == "tenant-project"


@pytest.mark.unit
def test_get_project_sandbox_missing_sandbox_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.get_project_sandbox = AsyncMock(return_value=None)
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Sandbox not found. Use POST to create one."
    assert "proj-1" not in response.text


@pytest.mark.unit
def test_ensure_project_sandbox_invalid_profile_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox",
        json={"profile": "secret-profile"},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "Invalid sandbox profile"
    assert "secret-profile" not in response.text


@pytest.mark.unit
def test_project_sandbox_health_missing_sandbox_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.health_check = AsyncMock(return_value=False)
    lifecycle_service.get_project_sandbox = AsyncMock(return_value=None)
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/health")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Sandbox not found"
    assert "proj-1" not in response.text


@pytest.mark.unit
def test_project_sandbox_health_error_log_omits_ids_and_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.health_check = AsyncMock(
        side_effect=RuntimeError("health check secret for proj-1")
    )
    lifecycle_service.get_project_sandbox = AsyncMock()
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/health")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Health check failed"
    assert "proj-1" not in response.text
    assert "health check secret" not in response.text
    assert "Health check failed" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "proj-1" not in caplog.text
    assert "health check secret" not in caplog.text


@pytest.mark.unit
def test_project_sandbox_stats_missing_sandbox_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.get_project_sandbox = AsyncMock(return_value=None)
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/stats")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Sandbox not found"
    assert "proj-1" not in response.text


@pytest.mark.unit
def test_project_sandbox_stats_error_log_omits_ids_and_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.get_project_sandbox = AsyncMock(return_value=_sandbox_info())
    adapter = SimpleNamespace(
        get_sandbox_stats=AsyncMock(side_effect=RuntimeError("stats secret for proj-1"))
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_sandbox_adapter] = lambda: adapter
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/stats")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Stats query failed"
    assert "proj-1" not in response.text
    assert "stats secret" not in response.text
    assert "Failed to get sandbox stats" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "proj-1" not in caplog.text
    assert "stats secret" not in caplog.text


@pytest.mark.unit
def test_execute_tool_error_log_omits_ids_and_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.execute_tool = AsyncMock(
        side_effect=RuntimeError("execute secret for proj-1")
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/execute",
        json={"tool_name": "bash", "arguments": {"cmd": "true"}, "timeout": 1},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Execution failed"
    assert "proj-1" not in response.text
    assert "execute secret" not in response.text
    assert "Tool execution failed" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "proj-1" not in caplog.text
    assert "execute secret" not in caplog.text


@pytest.mark.unit
def test_terminate_project_sandbox_missing_sandbox_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.terminate_project_sandbox = AsyncMock(return_value=False)
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    response = sandbox_http_client.delete("/api/v1/projects/proj-1/sandbox")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Sandbox not found"
    assert "proj-1" not in response.text


@pytest.mark.unit
def test_terminate_project_sandbox_error_log_omits_ids_and_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.terminate_project_sandbox = AsyncMock(
        side_effect=RuntimeError("terminate secret for proj-1")
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.delete("/api/v1/projects/proj-1/sandbox")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Termination failed"
    assert "proj-1" not in response.text
    assert "terminate secret" not in response.text
    assert "Failed to terminate sandbox" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "proj-1" not in caplog.text
    assert "terminate secret" not in caplog.text


@pytest.mark.unit
def test_terminate_project_sandbox_publish_error_log_omits_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.terminate_project_sandbox = AsyncMock(return_value=True)
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_event_publisher] = (
        lambda: _FailingSandboxLifecycleEventPublisher()
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.delete("/api/v1/projects/proj-1/sandbox")

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to publish sandbox_terminated event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "sandbox terminated secret" not in caplog.text
    assert "proj-1" not in caplog.text


@pytest.mark.unit
def test_terminate_project_sandbox_broadcast_error_log_omits_exception_text(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.terminate_project_sandbox = AsyncMock(return_value=True)
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: _FailingSandboxStateBroadcastManager("broadcast terminated secret for proj-1"),
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.delete("/api/v1/projects/proj-1/sandbox")

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to broadcast sandbox state via WebSocket" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "broadcast terminated secret" not in caplog.text
    assert "proj-1" not in caplog.text


@pytest.mark.unit
def test_sync_project_sandbox_error_log_omits_ids_and_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.sync_sandbox_status = AsyncMock(
        side_effect=RuntimeError("sync secret for proj-1")
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/sync")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Sync failed"
    assert "proj-1" not in response.text
    assert "sync secret" not in response.text
    assert "Failed to sync sandbox status" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "proj-1" not in caplog.text
    assert "sync secret" not in caplog.text


@pytest.mark.unit
def test_restart_project_sandbox_broadcasts_project_tenant_from_access_check(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restart events must be delivered to the project tenant channel."""

    async def allow_access(*_args, **_kwargs) -> str:
        return "tenant-project"

    monkeypatch.setattr(router_mod, "verify_project_access", allow_access)

    lifecycle_service = AsyncMock()
    lifecycle_service.restart_project_sandbox = AsyncMock(
        return_value=router_mod.SandboxInfo(
            sandbox_id="sandbox-1",
            project_id="proj-1",
            tenant_id="tenant-project",
            status="running",
        )
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    manager = AsyncMock()
    manager.broadcast_sandbox_state = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: manager,
    )

    response = sandbox_http_client.post("/api/v1/projects/proj-1/sandbox/restart")

    assert response.status_code == status.HTTP_200_OK
    lifecycle_service.restart_project_sandbox.assert_awaited_once_with("proj-1")
    manager.broadcast_sandbox_state.assert_awaited_once()
    assert manager.broadcast_sandbox_state.await_args.kwargs["tenant_id"] == "tenant-project"


@pytest.mark.unit
def test_restart_project_sandbox_error_log_omits_ids_and_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.restart_project_sandbox = AsyncMock(
        side_effect=RuntimeError("restart secret for proj-1")
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post("/api/v1/projects/proj-1/sandbox/restart")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Restart failed"
    assert "proj-1" not in response.text
    assert "restart secret" not in response.text
    assert "Failed to restart sandbox" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "proj-1" not in caplog.text
    assert "restart secret" not in caplog.text


@pytest.mark.unit
def test_restart_project_sandbox_publish_error_log_omits_exception_text(
    sandbox_http_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.restart_project_sandbox = AsyncMock(return_value=_sandbox_info())
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_event_publisher] = (
        lambda: _FailingSandboxLifecycleEventPublisher()
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post("/api/v1/projects/proj-1/sandbox/restart")

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to publish sandbox_restarted event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "sandbox restarted secret" not in caplog.text
    assert "proj-1" not in caplog.text


@pytest.mark.unit
def test_restart_project_sandbox_broadcast_error_log_omits_exception_text(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.restart_project_sandbox = AsyncMock(return_value=_sandbox_info())
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: _FailingSandboxStateBroadcastManager("broadcast restarted secret for proj-1"),
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.post("/api/v1/projects/proj-1/sandbox/restart")

    assert response.status_code == status.HTTP_200_OK
    assert "Failed to broadcast sandbox state via WebSocket" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "broadcast restarted secret" not in caplog.text
    assert "proj-1" not in caplog.text


@pytest.mark.unit
def test_list_project_sandboxes_invalid_status_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    response = sandbox_http_client.get("/api/v1/projects/sandboxes?status=secret-status")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "Invalid sandbox status"
    assert "secret-status" not in response.text


@pytest.mark.unit
def test_stop_project_desktop_missing_sandbox_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.get_project_sandbox = AsyncMock(return_value=None)
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    response = sandbox_http_client.delete("/api/v1/projects/proj-1/sandbox/desktop")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Sandbox not found"
    assert "proj-1" not in response.text


@pytest.mark.unit
def test_stop_project_terminal_missing_sandbox_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.get_project_sandbox = AsyncMock(return_value=None)
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    response = sandbox_http_client.delete("/api/v1/projects/proj-1/sandbox/terminal")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Sandbox not found"
    assert "proj-1" not in response.text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "service_method"),
    [
        ("post", "/api/v1/projects/proj-1/sandbox/desktop", "ensure_sandbox_running"),
        ("delete", "/api/v1/projects/proj-1/sandbox/desktop", "get_project_sandbox"),
        ("post", "/api/v1/projects/proj-1/sandbox/terminal", "ensure_sandbox_running"),
        ("delete", "/api/v1/projects/proj-1/sandbox/terminal", "get_project_sandbox"),
    ],
)
def test_project_interactive_lifecycle_requires_project_access(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    service_method: str,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.ensure_sandbox_running = AsyncMock()
    lifecycle_service.get_project_sandbox = AsyncMock()
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    async def deny_access(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=403, detail="Access denied to project")

    monkeypatch.setattr(router_mod, "verify_project_access", deny_access)

    response = getattr(sandbox_http_client, method)(path)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["detail"] == "Access denied to project"
    getattr(lifecycle_service, service_method).assert_not_awaited()


@pytest.mark.unit
def test_desktop_http_proxy_requires_project_access(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle_service = AsyncMock()
    lifecycle_service.get_project_sandbox = AsyncMock()
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    async def deny_access(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=403, detail="Access denied to project")

    monkeypatch.setattr(router_mod, "verify_project_access", deny_access)

    response = sandbox_http_client.get("/api/v1/projects/proj-1/sandbox/desktop/proxy/")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["detail"] == "Access denied to project"
    lifecycle_service.get_project_sandbox.assert_not_awaited()


@pytest.mark.unit
def test_desktop_http_proxy_sanitizes_upstream_connection_errors(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Desktop HTTP proxy should not log upstream URLs or connection details."""
    lifecycle_service = AsyncMock()
    lifecycle_service.get_project_sandbox = AsyncMock(
        return_value=SimpleNamespace(desktop_url="http://127.0.0.1:6080")
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    class _FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            req = httpx.Request("GET", "https://127.0.0.1:6080/app.js?debug=query-secret")
            raise httpx.RequestError("desktop connection secret", request=req)

    monkeypatch.setattr("httpx.AsyncClient", _FailingAsyncClient)
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.get(
        "/api/v1/projects/proj-1/sandbox/desktop/proxy/app.js?debug=query-secret&token=ms_sk_test"
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert response.json()["detail"] == "Failed to connect to desktop service"
    assert "desktop connection secret" not in response.text
    assert "127.0.0.1" not in response.text
    assert "query-secret" not in response.text
    assert "Failed to proxy desktop request" in caplog.text
    assert "has_target_url=True" in caplog.text
    assert "error_type=RequestError" in caplog.text
    assert "desktop connection secret" not in caplog.text
    assert "127.0.0.1" not in caplog.text
    assert "query-secret" not in caplog.text
    assert "proj-1" not in caplog.text


@pytest.mark.unit
async def test_desktop_websocket_proxy_requires_project_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    service = SimpleNamespace(get_project_sandbox=AsyncMock())

    async def deny_access(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=403, detail="Access denied to project")

    monkeypatch.setattr(router_mod, "verify_project_access", deny_access)

    await router_mod.proxy_project_desktop_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "Access denied to project"
    service.get_project_sandbox.assert_not_awaited()


@pytest.mark.unit
async def test_terminal_websocket_proxy_requires_project_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    service = SimpleNamespace(get_project_sandbox=AsyncMock())

    async def deny_access(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=403, detail="Access denied to project")

    monkeypatch.setattr(router_mod, "verify_project_access", deny_access)

    await router_mod.proxy_project_terminal_websocket(
        websocket=websocket,
        project_id="proj-1",
        session_id=None,
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "Access denied to project"
    service.get_project_sandbox.assert_not_awaited()


@pytest.mark.unit
async def test_mcp_websocket_proxy_requires_project_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    service = SimpleNamespace(get_project_sandbox=AsyncMock())

    async def deny_access(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=403, detail="Access denied to project")

    monkeypatch.setattr(router_mod, "verify_project_access", deny_access)

    await router_mod.proxy_project_mcp_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "Access denied to project"
    service.get_project_sandbox.assert_not_awaited()


@pytest.mark.unit
async def test_desktop_websocket_proxy_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    websocket = _FakeWebSocket()
    service = _SandboxService(desktop_url="http://desktop.local")

    async def fail_connect(*_args, **_kwargs):
        raise RuntimeError("desktop secret token")

    monkeypatch.setattr(router_mod, "_connect_desktop_upstream", fail_connect)
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    await router_mod.proxy_project_desktop_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.sent_json == [{"error": "Desktop WebSocket proxy failed"}]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True
    assert "Desktop WebSocket proxy error" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "desktop secret token" not in caplog.text
    assert "proj-1" not in caplog.text


@pytest.mark.unit
async def test_desktop_websocket_proxy_upgrades_stale_http_url(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    websocket = _FakeWebSocket()
    service = _SandboxService(desktop_url="http://desktop.local:16080")
    upstream = SimpleNamespace(close=AsyncMock())
    captured: dict[str, str] = {}

    async def fake_connect(ws_target: str, desktop_url: str) -> object:
        captured["ws_target"] = ws_target
        captured["desktop_url"] = desktop_url
        return upstream

    async def fake_relay_pair(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(router_mod, "_connect_desktop_upstream", fake_connect)
    monkeypatch.setattr(router_mod, "_run_ws_relay_pair", fake_relay_pair)
    caplog.set_level(
        logging.INFO,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    await router_mod.proxy_project_desktop_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.accepted_subprotocol == "binary"
    assert captured == {
        "ws_target": "wss://desktop.local:16080/websockify",
        "desktop_url": "http://desktop.local:16080",
    }
    upstream.close.assert_awaited_once()
    assert websocket.closed is True
    assert "Desktop WS proxy" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "has_desktop_url=True" in caplog.text
    assert "has_ws_target=True" in caplog.text
    assert "proj-1" not in caplog.text
    assert "desktop.local" not in caplog.text


@pytest.mark.unit
async def test_connect_desktop_upstream_uses_plain_ws_without_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_connect(uri: str, **kwargs: object) -> object:
        captured["uri"] = uri
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(websockets, "connect", fake_connect)

    await router_mod._connect_desktop_upstream(
        "ws://desktop.local/",
        "http://desktop.local",
    )

    assert captured["uri"] == "ws://desktop.local/"
    assert captured["ssl"] is None
    assert captured["additional_headers"] == {"Origin": "http://desktop.local"}


@pytest.mark.unit
async def test_connect_desktop_upstream_uses_ssl_for_wss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_connect(uri: str, **kwargs: object) -> object:
        captured["uri"] = uri
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(websockets, "connect", fake_connect)

    await router_mod._connect_desktop_upstream(
        "wss://desktop.local/",
        "http://desktop.local",
    )

    assert captured["uri"] == "wss://desktop.local/"
    assert captured["ssl"] is not None
    assert captured["additional_headers"] == {"Origin": "https://desktop.local"}


@pytest.mark.unit
async def test_desktop_websocket_missing_sandbox_reason_is_sanitized() -> None:
    websocket = _FakeWebSocket()
    service = SimpleNamespace(get_project_sandbox=AsyncMock(return_value=None))

    await router_mod.proxy_project_desktop_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "Sandbox not found"
    assert "proj-1" not in str(websocket.close_reason)


@pytest.mark.unit
async def test_desktop_websocket_missing_desktop_reason_is_sanitized() -> None:
    websocket = _FakeWebSocket()
    service = _SandboxService(desktop_url=None)

    await router_mod.proxy_project_desktop_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "Desktop service is not running"
    assert "proj-1" not in str(websocket.close_reason)


@pytest.mark.unit
async def test_terminal_websocket_accepts_auth_subprotocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.adapters.secondary.sandbox import terminal_proxy

    websocket = _FakeWebSocket(headers={"sec-websocket-protocol": "memstack.auth, ms_sk_test"})
    service = _SandboxService(terminal_url="ws://terminal.local")
    proxy = SimpleNamespace(get_session=Mock(return_value=None))
    monkeypatch.setattr(terminal_proxy, "get_terminal_proxy", lambda: proxy)

    await router_mod.proxy_project_terminal_websocket(
        websocket=websocket,
        project_id="proj-1",
        session_id="missing-session",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.accepted_subprotocol == "memstack.auth"
    assert websocket.sent_json == [{"type": "error", "message": "Session not found"}]
    assert websocket.closed is True


@pytest.mark.unit
async def test_http_service_websocket_proxy_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    websocket = _FakeWebSocket()
    event_publisher = AsyncMock()
    event_publisher.publish_http_service_error = AsyncMock()

    router_mod._http_service_registry.clear()
    router_mod._http_service_registry.setdefault("proj-1", {})["svc-int"] = (
        router_mod.HttpServiceProxyInfo(
            service_id="svc-int",
            name="internal",
            source_type="sandbox_internal",
            service_url="http://127.0.0.1:3000",
            project_id="proj-1",
            sandbox_id="sandbox-1",
            internal_port=5173,
            status="running",
            preview_url="/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/",
            updated_at="2026-01-01T00:00:00Z",
        )
    )

    async def allow_access(*_args, **_kwargs) -> None:
        return None

    async def fail_connect(*_args, **_kwargs):
        raise RuntimeError("http service secret token")

    monkeypatch.setattr(router_mod, "verify_project_access", allow_access)
    monkeypatch.setattr(router_mod, "_connect_http_service_upstream", fail_connect)
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    await router_mod.proxy_project_http_service_websocket(
        websocket=websocket,
        project_id="proj-1",
        service_id="svc-int",
        path="ws",
        current_user=SimpleNamespace(id="user-1"),
        event_publisher=event_publisher,
        redis_client=None,
        db=SimpleNamespace(),
    )

    assert websocket.sent_json == [{"error": "HTTP service WebSocket proxy failed"}]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True
    assert websocket.close_code == 1011
    assert websocket.close_reason == "HTTP service WS proxy failure"
    event_publisher.publish_http_service_error.assert_awaited_once()
    error_kwargs = event_publisher.publish_http_service_error.await_args.kwargs
    assert error_kwargs["service_id"] == "svc-int"
    assert error_kwargs["error_message"] == "RuntimeError"
    assert "secret" not in str(error_kwargs)
    assert "HTTP service WS proxy error" in caplog.text
    assert "has_service_id=True" in caplog.text
    assert "has_ws_target=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "http service secret token" not in caplog.text
    assert "127.0.0.1" not in caplog.text
    assert "svc-int" not in caplog.text


@pytest.mark.unit
async def test_terminal_websocket_proxy_sanitizes_internal_session_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    service = _SandboxService(terminal_url="http://terminal.local")

    class FailingTerminalProxy:
        async def create_session(self, *_args, **_kwargs):
            raise ValueError("terminal docker socket secret")

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.sandbox.terminal_proxy.get_terminal_proxy",
        lambda: FailingTerminalProxy(),
    )

    await router_mod.proxy_project_terminal_websocket(
        websocket=websocket,
        project_id="proj-1",
        session_id=None,
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.sent_json == [
        {"type": "error", "message": "Failed to create terminal session"}
    ]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True


@pytest.mark.unit
async def test_terminal_websocket_missing_sandbox_reason_is_sanitized() -> None:
    websocket = _FakeWebSocket()
    service = SimpleNamespace(get_project_sandbox=AsyncMock(return_value=None))

    await router_mod.proxy_project_terminal_websocket(
        websocket=websocket,
        project_id="proj-1",
        session_id=None,
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "Sandbox not found"
    assert "proj-1" not in str(websocket.close_reason)


@pytest.mark.unit
async def test_terminal_websocket_missing_terminal_reason_is_sanitized() -> None:
    websocket = _FakeWebSocket()
    service = _SandboxService(terminal_url=None)

    await router_mod.proxy_project_terminal_websocket(
        websocket=websocket,
        project_id="proj-1",
        session_id=None,
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "Terminal service is not running"
    assert "proj-1" not in str(websocket.close_reason)


@pytest.mark.unit
async def test_mcp_websocket_proxy_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    websocket = _FakeWebSocket()
    service = _SandboxService(websocket_url="ws://mcp.local")

    async def fail_connect(*_args, **_kwargs):
        raise RuntimeError("mcp secret token")

    monkeypatch.setattr(router_mod, "_connect_mcp_upstream", fail_connect)
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    await router_mod.proxy_project_mcp_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.sent_json == [{"error": "MCP WebSocket proxy failed"}]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True
    assert "MCP WebSocket proxy error" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "mcp secret token" not in caplog.text
    assert "proj-1" not in caplog.text


@pytest.mark.unit
async def test_mcp_websocket_proxy_success_logs_omit_target_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    websocket = _FakeWebSocket()
    service = _SandboxService(websocket_url="ws://mcp.local/secret")
    upstream = SimpleNamespace(close=AsyncMock())

    async def fake_connect(_ws_target: str) -> object:
        return upstream

    async def fake_relay_pair(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(router_mod, "_connect_mcp_upstream", fake_connect)
    monkeypatch.setattr(router_mod, "_run_ws_relay_pair", fake_relay_pair)
    caplog.set_level(
        logging.INFO,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    await router_mod.proxy_project_mcp_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.accepted is True
    upstream.close.assert_awaited_once()
    assert websocket.closed is True
    assert "MCP WS proxy" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "has_ws_target=True" in caplog.text
    assert "proj-1" not in caplog.text
    assert "ws://mcp.local/secret" not in caplog.text


@pytest.mark.unit
async def test_mcp_websocket_missing_sandbox_reason_is_sanitized() -> None:
    websocket = _FakeWebSocket()
    service = SimpleNamespace(get_project_sandbox=AsyncMock(return_value=None))

    await router_mod.proxy_project_mcp_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "Sandbox not found"
    assert "proj-1" not in str(websocket.close_reason)


@pytest.mark.unit
async def test_mcp_websocket_missing_mcp_reason_is_sanitized() -> None:
    websocket = _FakeWebSocket()
    service = _SandboxService(websocket_url=None)

    await router_mod.proxy_project_mcp_websocket(
        websocket=websocket,
        project_id="proj-1",
        current_user=SimpleNamespace(id="user-1"),
        service=service,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "MCP service is not running"
    assert "proj-1" not in str(websocket.close_reason)


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
def test_register_internal_http_service_uses_project_tenant_from_access_check(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal preview registration must resolve sandboxes under the project tenant."""

    async def allow_access(*_args, **_kwargs) -> str:
        return "tenant-project"

    monkeypatch.setattr(router_mod, "verify_project_access", allow_access)

    lifecycle_service = AsyncMock()
    lifecycle_service.ensure_sandbox_running = AsyncMock(
        return_value=SimpleNamespace(sandbox_id="sandbox-1")
    )
    sandbox_http_client.app.dependency_overrides[router_mod.get_lifecycle_service] = (
        lambda: lifecycle_service
    )

    manager = AsyncMock()
    manager.broadcast_sandbox_state = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        router_mod, "_resolve_sandbox_container_ip", AsyncMock(return_value="10.0.0.2")
    )

    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services",
        json={
            "service_id": "vite",
            "name": "Vite",
            "source_type": "sandbox_internal",
            "internal_port": 5173,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    lifecycle_service.ensure_sandbox_running.assert_awaited_once()
    assert lifecycle_service.ensure_sandbox_running.await_args.kwargs["tenant_id"] == (
        "tenant-project"
    )
    manager.broadcast_sandbox_state.assert_awaited_once()
    assert manager.broadcast_sandbox_state.await_args.kwargs["tenant_id"] == "tenant-project"


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
    assert error_kwargs["error_message"] == "RuntimeError"
    assert "persist failed" not in error_kwargs["error_message"]


@pytest.mark.unit
def test_stop_http_service_not_found(sandbox_http_client: TestClient) -> None:
    """Deleting a missing service returns 404."""
    response = sandbox_http_client.delete("/api/v1/projects/proj-1/sandbox/http-services/missing")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "HTTP service not found"
    assert "missing" not in response.text
    assert "proj-1" not in response.text


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
    assert response.json()["detail"] == "HTTP service not found"
    assert "nope" not in response.text
    assert "proj-1" not in response.text


@pytest.mark.unit
def test_http_proxy_returns_502_when_upstream_fails(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
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
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.get(
        "/api/v1/projects/proj-1/sandbox/http-services/svc-int/proxy/"
    )
    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert response.json()["detail"] == "Failed to connect to HTTP service"
    assert "127.0.0.1" not in response.text
    assert "connection refused" not in response.text
    event_publisher.publish_http_service_error.assert_awaited_once()
    error_kwargs = event_publisher.publish_http_service_error.await_args.kwargs
    assert error_kwargs["project_id"] == "proj-1"
    assert error_kwargs["service_id"] == "svc-int"
    assert error_kwargs["service_name"] == "internal"
    assert error_kwargs["error_message"] == "RuntimeError"
    assert "HTTP service proxy error" in caplog.text
    assert "has_service_id=True" in caplog.text
    assert "has_target_url=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "connection refused" not in caplog.text
    assert "127.0.0.1" not in caplog.text
    assert "svc-int" not in caplog.text


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
def test_create_preview_session_missing_service_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    """Preview-session 404 should not echo service or project identifiers."""
    response = sandbox_http_client.post(
        "/api/v1/projects/proj-1/sandbox/http-services/missing/preview-session"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "HTTP service not found"
    assert "missing" not in response.text
    assert "proj-1" not in response.text


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
def test_host_preview_proxy_missing_service_is_sanitized(
    sandbox_http_client: TestClient,
) -> None:
    """Host preview 404 should not echo preview host labels."""
    response = sandbox_http_client.get(
        "/",
        headers={"host": "missing.proj-1.preview.localhost:8000"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "HTTP service not found"
    assert "missing" not in response.text
    assert "proj-1" not in response.text


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


@pytest.mark.unit
def test_host_preview_proxy_sanitizes_upstream_connection_errors(
    sandbox_http_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Host-based preview should not leak upstream URL or connection details."""
    event_publisher = AsyncMock()
    event_publisher.publish_http_service_error = AsyncMock()
    sandbox_http_client.app.dependency_overrides[router_mod.get_event_publisher] = (
        lambda: event_publisher
    )

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
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    response = sandbox_http_client.get(
        "/",
        headers={"host": "svc-int.proj-1.preview.localhost:8000"},
        cookies={router_mod._PREVIEW_SESSION_COOKIE_NAME: token},
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert response.json()["detail"] == "Failed to connect to HTTP service"
    assert "127.0.0.1" not in response.text
    assert "connection refused" not in response.text
    event_publisher.publish_http_service_error.assert_awaited_once()
    error_kwargs = event_publisher.publish_http_service_error.await_args.kwargs
    assert error_kwargs["service_id"] == "svc-int"
    assert error_kwargs["error_message"] == "RuntimeError"
    assert "connection refused" not in str(error_kwargs)
    assert "127.0.0.1" not in str(error_kwargs)
    assert "HTTP preview host proxy error" in caplog.text
    assert "has_service_id=True" in caplog.text
    assert "has_target_url=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "connection refused" not in caplog.text
    assert "127.0.0.1" not in caplog.text
    assert "svc-int" not in caplog.text


@pytest.mark.unit
async def test_http_service_websocket_missing_service_reason_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Path-based WebSocket preview should not echo missing IDs in close reasons."""
    websocket = _FakeWebSocket()

    async def allow_access(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(router_mod, "verify_project_access", allow_access)

    await router_mod.proxy_project_http_service_websocket(
        websocket=websocket,
        project_id="proj-1",
        service_id="missing",
        path="ws",
        current_user=SimpleNamespace(id="user-1"),
        event_publisher=None,
        redis_client=None,
        db=SimpleNamespace(),
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "HTTP service not found"


@pytest.mark.unit
async def test_host_preview_websocket_sanitizes_upstream_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Host-based WebSocket preview should not leak upstream URL or connection details."""
    token = router_mod._create_preview_session_token("proj-1", "svc-int", "user-1")
    websocket = _FakeWebSocket(
        headers={"host": "svc-int.proj-1.preview.localhost:8000"},
        cookies={router_mod._PREVIEW_SESSION_COOKIE_NAME: token},
        query_items=[("debug", "query-secret")],
    )
    event_publisher = AsyncMock()
    event_publisher.publish_http_service_error = AsyncMock()

    router_mod._http_service_registry.clear()
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

    async def fail_connect(*_args, **_kwargs):
        raise RuntimeError("host preview websocket secret")

    monkeypatch.setattr(router_mod, "_connect_http_service_upstream", fail_connect)
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.project_sandbox",
    )

    await router_mod.proxy_project_http_service_preview_host_websocket(
        websocket=websocket,
        path="socket",
        event_publisher=event_publisher,
        redis_client=None,
    )

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.close_code == 1011
    assert websocket.close_reason == "HTTP preview host WS proxy failure"
    event_publisher.publish_http_service_error.assert_awaited_once()
    error_kwargs = event_publisher.publish_http_service_error.await_args.kwargs
    assert error_kwargs["service_id"] == "svc-int"
    assert error_kwargs["error_message"] == "RuntimeError"
    assert "host preview websocket secret" not in str(error_kwargs)
    assert "127.0.0.1" not in str(error_kwargs)
    assert "query-secret" not in str(error_kwargs)
    assert "HTTP preview host WS proxy error" in caplog.text
    assert "has_service_id=True" in caplog.text
    assert "has_ws_target=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "host preview websocket secret" not in caplog.text
    assert "127.0.0.1" not in caplog.text
    assert "query-secret" not in caplog.text
    assert "svc-int" not in caplog.text


@pytest.mark.unit
async def test_host_preview_websocket_missing_service_reason_is_sanitized() -> None:
    """Host-based WebSocket preview should not echo missing IDs in close reasons."""
    websocket = _FakeWebSocket(headers={"host": "missing.proj-1.preview.localhost:8000"})

    await router_mod.proxy_project_http_service_preview_host_websocket(
        websocket=websocket,
        path="ws",
        event_publisher=None,
        redis_client=None,
    )

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "HTTP service not found"
