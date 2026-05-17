from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers import terminal as terminal_router
from src.infrastructure.adapters.primary.web.routers.terminal import (
    CreateTerminalRequest,
    _resolve_terminal_session,
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
async def test_resolve_terminal_session_sanitizes_creation_errors() -> None:
    class FailingProxy:
        async def create_session(self, *_args: object, **_kwargs: object) -> object:
            raise ValueError("docker socket secret")

    websocket = _FakeWebSocket()

    result = await _resolve_terminal_session(
        proxy=FailingProxy(),
        websocket=websocket,
        sandbox_id="sandbox-1",
        session_id=None,
    )

    assert result is None
    assert websocket.sent_json == [
        {"type": "error", "message": "Failed to create terminal session"}
    ]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True


@pytest.mark.unit
async def test_terminal_websocket_sanitizes_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
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

    await terminal_router.terminal_websocket(
        websocket=websocket,
        sandbox_id="sandbox-1",
        session_id=None,
    )

    assert websocket.sent_json == [{"type": "error", "message": "Terminal WebSocket failed"}]
    assert "secret" not in str(websocket.sent_json)
    assert websocket.closed is True


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
