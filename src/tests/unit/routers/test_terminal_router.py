from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, WebSocketDisconnect, status
from starlette.datastructures import Headers

from src.infrastructure.adapters.primary.web.routers import terminal as terminal_router
from src.infrastructure.adapters.primary.web.routers.terminal import (
    CreateTerminalRequest,
    _read_terminal_output,
    _resolve_terminal_session,
    get_event_publisher,
    get_project_id_from_sandbox,
)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent_json: list[object] = []
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.accepted = False
        self.accepted_subprotocol: str | None = None
        self.headers = Headers(raw=[])

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted = True
        self.accepted_subprotocol = subprotocol

    async def send_json(self, data: object) -> None:
        self.sent_json.append(data)

    async def close(
        self,
        code: int | None = None,
        reason: str | None = None,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class _ScalarOneResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> str | None:
        return self._value


class _AccessSession:
    def __init__(self, values: list[str | None]) -> None:
        self._values = iter(values)

    async def execute(self, _statement: object) -> _ScalarOneResult:
        return _ScalarOneResult(next(self._values))


def _allow_terminal_websocket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        terminal_router,
        "authenticate_websocket_or_close",
        AsyncMock(return_value=("user-1", "tenant-1")),
    )
    monkeypatch.setattr(
        terminal_router,
        "_find_authorized_terminal_project_id",
        AsyncMock(return_value="project-1"),
    )


@pytest.mark.unit
async def test_require_terminal_sandbox_access_allows_project_member() -> None:
    project_id = await terminal_router.require_terminal_sandbox_access(
        sandbox_id="sandbox-1",
        current_user=SimpleNamespace(id="user-1"),
        db=_AccessSession(["project-1", "project-1"]),
    )

    assert project_id == "project-1"


@pytest.mark.unit
async def test_require_terminal_sandbox_access_rejects_foreign_project() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await terminal_router.require_terminal_sandbox_access(
            sandbox_id="sandbox-1",
            current_user=SimpleNamespace(id="user-1"),
            db=_AccessSession(["project-1", None]),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
def test_terminal_rest_routes_require_sandbox_membership() -> None:
    protected_paths = {
        "/api/v1/terminal/{sandbox_id}/create",
        "/api/v1/terminal/{sandbox_id}/sessions",
        "/api/v1/terminal/{sandbox_id}/sessions/{session_id}",
    }
    protected_routes = [
        route for route in terminal_router.router.routes if route.path in protected_paths
    ]

    assert {route.path for route in protected_routes} == protected_paths
    for route in protected_routes:
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        assert terminal_router.require_terminal_sandbox_access in dependency_calls


@pytest.mark.unit
async def test_resolve_terminal_session_sanitizes_creation_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingProxy:
        async def create_session(self, *_args: object, **_kwargs: object) -> object:
            raise ValueError("docker socket secret")

    websocket = _FakeWebSocket()
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    result = await _resolve_terminal_session(
        proxy=FailingProxy(),
        websocket=websocket,
        sandbox_id="sandbox-secret",
        session_id=None,
    )

    assert result is None
    assert websocket.sent_json == [
        {"type": "error", "message": "Failed to create terminal session"}
    ]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True
    assert "Failed to create terminal session" in caplog.text
    assert "has_sandbox_id=True" in caplog.text
    assert "error_type=ValueError" in caplog.text
    assert "sandbox-secret" not in caplog.text
    assert "docker socket secret" not in caplog.text


@pytest.mark.unit
async def test_terminal_websocket_sanitizes_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingProxy:
        async def create_session(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                session_id="session-1",
                container_id="sandbox-1",
                cols=80,
                rows=24,
                is_active=False,
            )

    websocket = _FakeWebSocket()
    _allow_terminal_websocket(monkeypatch)
    monkeypatch.setattr(terminal_router, "get_terminal_proxy", lambda: FailingProxy())
    monkeypatch.setattr(
        terminal_router,
        "_resolve_terminal_session",
        AsyncMock(side_effect=RuntimeError("terminal upstream secret")),
    )
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    await terminal_router.terminal_websocket(
        websocket=websocket,
        sandbox_id="sandbox-1",
        session_id=None,
        token=None,
        db=SimpleNamespace(),
    )

    assert websocket.sent_json == [{"type": "error", "message": "Terminal WebSocket failed"}]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True
    assert "Terminal WebSocket error" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal upstream secret" not in caplog.text


@pytest.mark.unit
async def test_terminal_websocket_disconnect_log_omits_session_id(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = SimpleNamespace(
        session_id="session-secret",
        container_id="sandbox-1",
        cols=80,
        rows=24,
        is_active=False,
    )

    class WorkingProxy:
        pass

    websocket = _FakeWebSocket()
    _allow_terminal_websocket(monkeypatch)
    monkeypatch.setattr(terminal_router, "get_terminal_proxy", lambda: WorkingProxy())
    monkeypatch.setattr(
        terminal_router,
        "_resolve_terminal_session",
        AsyncMock(return_value=session),
    )
    monkeypatch.setattr(
        terminal_router,
        "_read_terminal_output",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        terminal_router,
        "receive_json_with_limit",
        AsyncMock(side_effect=WebSocketDisconnect()),
    )
    caplog.set_level(
        logging.INFO,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    await terminal_router.terminal_websocket(
        websocket=websocket,
        sandbox_id="sandbox-1",
        session_id=None,
        token=None,
        db=SimpleNamespace(),
    )

    assert websocket.sent_json == [
        {
            "type": "connected",
            "session_id": "session-secret",
            "cols": 80,
            "rows": 24,
        }
    ]
    assert websocket.closed is True
    assert "WebSocket disconnected" in caplog.text
    assert "has_session_id=True" in caplog.text
    assert "session-secret" not in caplog.text


@pytest.mark.unit
async def test_terminal_websocket_rejects_missing_auth_before_terminal_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    terminal_proxy = AsyncMock()
    monkeypatch.setattr(terminal_router, "get_terminal_proxy", terminal_proxy)

    await terminal_router.terminal_websocket(
        websocket=websocket,
        sandbox_id="sandbox-1",
        session_id=None,
        token=None,
        db=SimpleNamespace(),
    )

    assert websocket.accepted is False
    assert websocket.closed is True
    assert websocket.close_code == 4003
    terminal_proxy.assert_not_called()


@pytest.mark.unit
async def test_terminal_websocket_rejects_foreign_sandbox_before_terminal_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    terminal_proxy = AsyncMock()
    monkeypatch.setattr(
        terminal_router,
        "authenticate_websocket_or_close",
        AsyncMock(return_value=("user-1", "tenant-1")),
    )
    monkeypatch.setattr(
        terminal_router,
        "_find_authorized_terminal_project_id",
        AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to sandbox",
            )
        ),
    )
    monkeypatch.setattr(terminal_router, "get_terminal_proxy", terminal_proxy)

    await terminal_router.terminal_websocket(
        websocket=websocket,
        sandbox_id="sandbox-foreign",
        session_id=None,
        token=None,
        db=SimpleNamespace(),
    )

    assert websocket.accepted is False
    assert websocket.closed is True
    assert websocket.close_code == status.WS_1008_POLICY_VIOLATION
    terminal_proxy.assert_not_called()


@pytest.mark.unit
async def test_read_terminal_output_error_log_omits_proxy_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingProxy:
        async def read_output(self, _session_id: str) -> str | None:
            raise RuntimeError("terminal output secret")

    websocket = _FakeWebSocket()
    session = SimpleNamespace(session_id="session-secret", is_active=True)
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    await _read_terminal_output(FailingProxy(), websocket, session)

    assert websocket.sent_json == []
    assert "Output reader error" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal output secret" not in caplog.text
    assert "session-secret" not in caplog.text


@pytest.mark.unit
async def test_get_project_id_from_sandbox_error_log_omits_sandbox_id_and_error_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingSandboxAdapter:
        async def get_sandbox(self, _sandbox_id: str) -> object:
            raise RuntimeError("sandbox lookup secret")

    monkeypatch.setattr(
        terminal_router,
        "get_sandbox_adapter",
        lambda: FailingSandboxAdapter(),
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    result = await get_project_id_from_sandbox("sandbox-secret")

    assert result is None
    assert "Could not get project_id from sandbox" in caplog.text
    assert "has_sandbox_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "sandbox-secret" not in caplog.text
    assert "sandbox lookup secret" not in caplog.text


@pytest.mark.unit
def test_get_event_publisher_error_log_omits_container_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingContainer:
        def sandbox_event_publisher(self) -> object:
            raise RuntimeError("event publisher secret")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=FailingContainer()))
    )
    monkeypatch.setattr(terminal_router, "_event_publisher", None)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    result = get_event_publisher(request)

    assert result is None
    assert terminal_router._event_publisher is None
    assert "Could not create event publisher" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "event publisher secret" not in caplog.text


@pytest.mark.unit
async def test_create_terminal_session_sanitizes_missing_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingSandboxAdapter:
        async def get_sandbox(self, _sandbox_id: str) -> object | None:
            return None

    monkeypatch.setattr(terminal_router, "get_sandbox_adapter", lambda: MissingSandboxAdapter())

    with pytest.raises(HTTPException) as exc_info:
        await terminal_router.create_terminal_session(
            sandbox_id="sandbox-secret",
            request=CreateTerminalRequest(),
            _user=SimpleNamespace(id="user-1"),
            event_publisher=None,
            project_id="project-1",
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Sandbox not found"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_create_terminal_session_sanitizes_proxy_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExistingSandboxAdapter:
        async def get_sandbox(self, _sandbox_id: str) -> object:
            return SimpleNamespace(project_path=None)

    class FailingProxy:
        async def create_session(self, *_args: object, **_kwargs: object) -> object:
            raise ValueError("container sandbox-secret not found")

    monkeypatch.setattr(terminal_router, "get_sandbox_adapter", lambda: ExistingSandboxAdapter())
    monkeypatch.setattr(terminal_router, "get_terminal_proxy", lambda: FailingProxy())

    with pytest.raises(HTTPException) as exc_info:
        await terminal_router.create_terminal_session(
            sandbox_id="sandbox-secret",
            request=CreateTerminalRequest(),
            _user=SimpleNamespace(id="user-1"),
            event_publisher=None,
            project_id="project-1",
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Terminal session not found"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_create_terminal_session_started_event_log_omits_publisher_error_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ExistingSandboxAdapter:
        async def get_sandbox(self, _sandbox_id: str) -> object:
            return SimpleNamespace(project_path=None)

    class WorkingProxy:
        async def create_session(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                session_id="session-secret",
                container_id="sandbox-secret",
                cols=80,
                rows=24,
                is_active=True,
            )

    event_publisher = SimpleNamespace(
        publish_terminal_started=AsyncMock(
            side_effect=RuntimeError("terminal started publisher secret")
        )
    )
    monkeypatch.setattr(terminal_router, "get_sandbox_adapter", lambda: ExistingSandboxAdapter())
    monkeypatch.setattr(terminal_router, "get_terminal_proxy", lambda: WorkingProxy())
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    response = await terminal_router.create_terminal_session(
        sandbox_id="sandbox-secret",
        request=CreateTerminalRequest(),
        _user=SimpleNamespace(id="user-1"),
        event_publisher=event_publisher,
        project_id="project-1",
    )

    assert response.session_id == "session-secret"
    event_publisher.publish_terminal_started.assert_awaited_once_with(
        project_id="project-1",
        sandbox_id="sandbox-secret",
        url="ws://localhost:7681/session-secret",
        port=7681,
        session_id="session-secret",
    )
    assert "Failed to publish terminal_started event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal started publisher secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text
    assert "session-secret" not in caplog.text


@pytest.mark.unit
async def test_close_terminal_session_stopped_event_log_omits_publisher_error_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = SimpleNamespace(
        session_id="session-secret",
        container_id="sandbox-secret",
        cols=80,
        rows=24,
        is_active=True,
    )

    class WorkingProxy:
        def get_session(self, _session_id: str) -> object:
            return session

        async def close_session(self, _session_id: str) -> bool:
            return True

    event_publisher = SimpleNamespace(
        publish_terminal_stopped=AsyncMock(
            side_effect=RuntimeError("terminal stopped publisher secret")
        )
    )
    monkeypatch.setattr(terminal_router, "get_terminal_proxy", lambda: WorkingProxy())
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    response = await terminal_router.close_terminal_session(
        sandbox_id="sandbox-secret",
        session_id="session-secret",
        _user=SimpleNamespace(id="user-1"),
        event_publisher=event_publisher,
        project_id="project-1",
    )

    assert response == {"success": True, "session_id": "session-secret"}
    event_publisher.publish_terminal_stopped.assert_awaited_once_with(
        project_id="project-1",
        sandbox_id="sandbox-secret",
        session_id="session-secret",
    )
    assert "Failed to publish terminal_stopped event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal stopped publisher secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text
    assert "session-secret" not in caplog.text


@pytest.mark.unit
async def test_create_terminal_session_error_log_omits_proxy_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ExistingSandboxAdapter:
        async def get_sandbox(self, _sandbox_id: str) -> object:
            return SimpleNamespace(project_path=None)

    class FailingProxy:
        async def create_session(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("terminal runtime secret")

    monkeypatch.setattr(terminal_router, "get_sandbox_adapter", lambda: ExistingSandboxAdapter())
    monkeypatch.setattr(terminal_router, "get_terminal_proxy", lambda: FailingProxy())
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.terminal",
    )

    with pytest.raises(HTTPException) as exc_info:
        await terminal_router.create_terminal_session(
            sandbox_id="sandbox-secret",
            request=CreateTerminalRequest(),
            _user=SimpleNamespace(id="user-1"),
            event_publisher=None,
            project_id="project-1",
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to create terminal session"
    assert "Failed to create terminal session" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal runtime secret" not in caplog.text
