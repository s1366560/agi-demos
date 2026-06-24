"""Unit tests for sandbox desktop and terminal service route hardening."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.sandbox import services as services_router
from src.infrastructure.adapters.primary.web.routers.sandbox.schemas import (
    DesktopStartRequest,
    TerminalStartRequest,
)


class FailingOrchestrator:
    async def start_desktop(self, sandbox_id: str, config: Any) -> Any:
        raise RuntimeError(f"internal desktop secret for {sandbox_id}")

    async def start_terminal(self, sandbox_id: str, config: Any) -> Any:
        raise RuntimeError(f"internal terminal secret for {sandbox_id}")


class SuccessfulOrchestrator:
    async def start_desktop(self, _sandbox_id: str, _config: Any) -> Any:
        return SimpleNamespace(
            running=True,
            url="http://desktop.local",
            display=":1",
            resolution="1280x720",
            port=6080,
            audio_enabled=False,
            dynamic_resize=True,
            encoding="tight",
        )

    async def stop_desktop(self, _sandbox_id: str) -> bool:
        return True

    async def start_terminal(self, _sandbox_id: str, _config: Any) -> Any:
        return SimpleNamespace(
            running=True,
            url="http://terminal.local",
            port=7681,
            pid=123,
            session_id="session-1",
        )

    async def stop_terminal(self, _sandbox_id: str) -> bool:
        return True


class FailingEventPublisher:
    async def publish_desktop_started(self, **_kwargs: Any) -> None:
        raise RuntimeError("desktop started secret")

    async def publish_desktop_stopped(self, **_kwargs: Any) -> None:
        raise RuntimeError("desktop stopped secret")

    async def publish_terminal_started(self, **_kwargs: Any) -> None:
        raise RuntimeError("terminal started secret")

    async def publish_terminal_stopped(self, **_kwargs: Any) -> None:
        raise RuntimeError("terminal stopped secret")


async def _allow_sandbox_access(**_kwargs: Any) -> tuple[SimpleNamespace, str]:
    return SimpleNamespace(project_id="project-1"), "project-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_desktop_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services_router, "assert_caller_owns_sandbox", _allow_sandbox_access)

    with pytest.raises(HTTPException) as exc_info:
        await services_router.start_desktop(
            sandbox_id="sandbox-secret",
            request=DesktopStartRequest(),
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=SimpleNamespace(),
            orchestrator=FailingOrchestrator(),
            event_publisher=None,
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to start desktop"
    assert "internal" not in exc_info.value.detail
    assert "sandbox-secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_desktop_publish_error_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(services_router, "assert_caller_owns_sandbox", _allow_sandbox_access)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.services",
    )

    response = await services_router.start_desktop(
        sandbox_id="sandbox-secret",
        request=DesktopStartRequest(),
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        adapter=SimpleNamespace(),
        orchestrator=SuccessfulOrchestrator(),
        event_publisher=FailingEventPublisher(),
        db=SimpleNamespace(),
    )

    assert response.running is True
    assert "Failed to publish desktop_started event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "desktop started secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_desktop_publish_error_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(services_router, "assert_caller_owns_sandbox", _allow_sandbox_access)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.services",
    )

    response = await services_router.stop_desktop(
        sandbox_id="sandbox-secret",
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        adapter=SimpleNamespace(),
        orchestrator=SuccessfulOrchestrator(),
        event_publisher=FailingEventPublisher(),
        db=SimpleNamespace(),
    )

    assert response.success is True
    assert "Failed to publish desktop_stopped event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "desktop stopped secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_terminal_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(services_router, "assert_caller_owns_sandbox", _allow_sandbox_access)
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.services",
    )

    with pytest.raises(HTTPException) as exc_info:
        await services_router.start_terminal(
            sandbox_id="sandbox-secret",
            request=TerminalStartRequest(),
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=SimpleNamespace(),
            orchestrator=FailingOrchestrator(),
            event_publisher=None,
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to start terminal"
    assert "internal" not in exc_info.value.detail
    assert "sandbox-secret" not in exc_info.value.detail
    target_records = [
        record
        for record in caplog.records
        if record.name == "src.infrastructure.adapters.primary.web.routers.sandbox.services"
        and record.levelno >= logging.ERROR
    ]
    assert len(target_records) == 1
    message = target_records[0].getMessage()
    assert "Failed to start terminal" in message
    assert "error_type=RuntimeError" in message
    assert "sandbox-secret" not in message
    assert "internal terminal secret" not in message
    assert target_records[0].exc_info is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_terminal_publish_error_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(services_router, "assert_caller_owns_sandbox", _allow_sandbox_access)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.services",
    )

    response = await services_router.start_terminal(
        sandbox_id="sandbox-secret",
        request=TerminalStartRequest(),
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        adapter=SimpleNamespace(),
        orchestrator=SuccessfulOrchestrator(),
        event_publisher=FailingEventPublisher(),
        db=SimpleNamespace(),
    )

    assert response.running is True
    assert "Failed to publish terminal_started event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal started secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_terminal_publish_error_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(services_router, "assert_caller_owns_sandbox", _allow_sandbox_access)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.services",
    )

    response = await services_router.stop_terminal(
        sandbox_id="sandbox-secret",
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        adapter=SimpleNamespace(),
        orchestrator=SuccessfulOrchestrator(),
        event_publisher=FailingEventPublisher(),
        db=SimpleNamespace(),
    )

    assert response.success is True
    assert "Failed to publish terminal_stopped event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "terminal stopped secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text
