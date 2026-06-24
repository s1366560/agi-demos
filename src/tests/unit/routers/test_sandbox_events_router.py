"""Unit tests for sandbox SSE event route hardening."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.adapters.primary.web.routers.sandbox import events as events_router


@pytest.mark.unit
async def test_sandbox_event_stream_error_log_omits_exception_and_project_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingEventBus:
        async def stream_read(self, **_kwargs: Any):
            raise RuntimeError("redis stream secret")
            yield {}

    event_publisher = SimpleNamespace(_event_bus=FailingEventBus())
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.events",
    )

    messages = [
        message
        async for message in events_router.sandbox_event_stream(
            project_id="project-secret",
            last_id="0",
            event_publisher=event_publisher,
        )
    ]

    assert messages == []
    assert "[SandboxSSE] Stream error" in caplog.text
    assert "has_project_id=True" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "redis stream secret" not in caplog.text
    assert "project-secret" not in caplog.text
    assert "sandbox:events:project-secret" not in caplog.text
