"""Unit tests for the async request queue."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.infrastructure.queue import request_queue
from src.infrastructure.queue.request_queue import QueuedRequest, QueueFullError, RequestQueue

pytestmark = pytest.mark.unit


async def _add(a: int, b: int = 0) -> int:
    return a + b


async def _raise_error() -> None:
    raise ValueError("boom")


async def _sleep() -> None:
    await asyncio.sleep(1)


async def test_get_next_request_uses_priority_then_age() -> None:
    queue = RequestQueue(max_concurrent=1)
    low = QueuedRequest("low", _add, (1,), {}, priority=0)
    high_newer = QueuedRequest("high-newer", _add, (2,), {}, priority=10)
    high_older = QueuedRequest("high-older", _add, (3,), {}, priority=10)
    high_older.created_at = high_newer.created_at.replace(year=high_newer.created_at.year - 1)
    queue._queue.extend([low, high_newer, high_older])

    assert queue._get_next_request() is high_older
    assert queue._get_next_request() is high_newer
    assert queue._get_next_request() is low
    assert queue._get_next_request() is None


async def test_enqueue_processes_request_and_reports_stats() -> None:
    queue = RequestQueue(max_concurrent=1, max_queue_size=5, request_timeout=1)
    queue.start()

    try:
        result = await queue.enqueue(_add, args=(2,), kwargs={"b": 3}, priority=1)
        stats = queue.get_stats()
    finally:
        await queue.stop()

    assert result == 5
    assert stats["queue_size"] == 0
    assert stats["processing"] == 0
    assert stats["workers"] == 1
    assert stats["running"] is True
    assert queue.get_stats()["running"] is False


async def test_enqueue_rejects_full_queue_without_starting_workers() -> None:
    queue = RequestQueue(max_concurrent=1, max_queue_size=0)

    with pytest.raises(QueueFullError, match="Request queue is full"):
        await queue.enqueue(_add)


async def test_worker_propagates_request_exceptions() -> None:
    queue = RequestQueue(max_concurrent=1, max_queue_size=5, request_timeout=1)
    queue.start()

    try:
        with pytest.raises(ValueError, match="boom"):
            await queue.enqueue(_raise_error)
    finally:
        await queue.stop()


async def test_worker_converts_timeout_to_timeout_error() -> None:
    queue = RequestQueue(max_concurrent=1, max_queue_size=5, request_timeout=0.01)
    queue.start()

    try:
        with pytest.raises(TimeoutError, match="Request timed out"):
            await queue.enqueue(_sleep)
    finally:
        await queue.stop()


async def test_start_and_stop_are_idempotent() -> None:
    queue = RequestQueue(max_concurrent=1, max_queue_size=5, request_timeout=1)

    await queue.stop()
    queue.start()
    queue.start()
    assert len(queue._workers) == 1

    await queue.stop()
    await queue.stop()
    assert queue.get_stats()["workers"] == 0


async def test_get_request_queue_builds_global_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        request_queue,
        "get_settings",
        lambda: SimpleNamespace(max_async_workers=1, llm_timeout=1),
    )
    monkeypatch.setattr(request_queue, "_request_queue", None)

    queue = request_queue.get_request_queue()

    try:
        assert queue.get_stats()["running"] is True
        assert queue.get_stats()["max_concurrent"] == 1
    finally:
        await queue.stop()
        monkeypatch.setattr(request_queue, "_request_queue", None)
