from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

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
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: object) -> None:
        self.sent_json.append(data)

    async def close(self, *args, **kwargs) -> None:
        self.closed = True


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
    )

    assert websocket.sent_json == [{"type": "error", "message": "Terminal WebSocket failed"}]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True
    assert "Terminal WebSocket error" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal upstream secret" not in caplog.text


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
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Terminal session not found"
    assert "secret" not in exc_info.value.detail


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
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to create terminal session"
    assert "Failed to create terminal session" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal runtime secret" not in caplog.text
