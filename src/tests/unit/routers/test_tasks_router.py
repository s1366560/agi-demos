from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers import tasks as tasks_router


class _FailingSession:
    async def __aenter__(self) -> _FailingSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, *_args: object) -> object:
        raise RuntimeError("internal stream secret")


@pytest.mark.unit
async def test_poll_task_updates_sanitizes_retry_exhaustion_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks_router,
        "async_session_factory",
        lambda: _FailingSession(),
    )
    monkeypatch.setattr(tasks_router.asyncio, "sleep", AsyncMock())

    events = [
        event
        async for event in tasks_router._poll_task_updates(
            task_id="task-1",
            last_progress=0,
            last_status="PROCESSING",
            retry_sleep_seconds=0,
            poll_sleep_seconds=0,
        )
    ]

    assert len(events) == 1
    assert events[0]["event"] == "error"
    payload = json.loads(events[0]["data"])
    assert payload == {
        "error": "Stream error",
        "message": "Task stream failed",
    }
    assert "internal" not in events[0]["data"]


class _MissingTaskSession:
    async def __aenter__(self) -> _MissingTaskSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, *_args: object) -> object:
        return SimpleNamespace(scalar_one_or_none=lambda: None)


@pytest.mark.unit
async def test_poll_task_updates_reports_missing_task_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks_router,
        "async_session_factory",
        lambda: _MissingTaskSession(),
    )

    events = [
        event
        async for event in tasks_router._poll_task_updates(
            task_id="task-1",
            last_progress=0,
            last_status="PROCESSING",
            retry_sleep_seconds=0,
            poll_sleep_seconds=0,
        )
    ]

    assert events == [
        {
            "event": "error",
            "data": json.dumps({"error": "Task disappeared from database"}),
        }
    ]
