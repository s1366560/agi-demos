"""Unit tests for websocket connection manager bridge task registration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from src.infrastructure.adapters.primary.web.websocket.connection_manager import ConnectionManager


class _StubTask:
    def __init__(self, *, done: bool = False) -> None:
        self._done = done
        self.cancelled = False

    def done(self) -> bool:
        return self._done

    def cancel(self) -> None:
        self.cancelled = True


def _make_task_with_bridge_message_id(message_id: str) -> _StubTask:
    task = _StubTask(done=False)
    task._bridge_message_id = message_id  # type: ignore[attr-defined]
    return task


def _task_factory(task: _StubTask) -> Callable[[], _StubTask]:
    return lambda: task


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_start_bridge_task_skips_when_active_bridge_exists() -> None:
    manager = ConnectionManager()
    existing_task = _StubTask(done=False)
    manager.bridge_tasks["session-existing"] = {"conv-1": existing_task}
    manager.active_connections["session-new"] = object()  # type: ignore[assignment]
    manager.subscriptions["session-new"] = {"conv-1"}
    new_task = _StubTask(done=False)

    started = await manager.try_start_bridge_task(
        session_id="session-new",
        conversation_id="conv-1",
        task_factory=_task_factory(new_task),
    )

    assert started is False
    assert "session-new" not in manager.bridge_tasks
    assert manager.bridge_tasks["session-existing"]["conv-1"] is existing_task


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_start_bridge_task_is_atomic_for_concurrent_calls() -> None:
    manager = ConnectionManager()
    manager.active_connections["session-a"] = object()  # type: ignore[assignment]
    manager.active_connections["session-b"] = object()  # type: ignore[assignment]
    manager.subscriptions["session-a"] = {"conv-1"}
    manager.subscriptions["session-b"] = {"conv-1"}
    created_tasks: list[tuple[str, _StubTask]] = []

    def _factory(session_id: str) -> Callable[[], _StubTask]:
        def _create_task() -> _StubTask:
            task = _StubTask(done=False)
            created_tasks.append((session_id, task))
            return task

        return _create_task

    started_a, started_b = await asyncio.gather(
        manager.try_start_bridge_task(
            session_id="session-a",
            conversation_id="conv-1",
            task_factory=_factory("session-a"),
        ),
        manager.try_start_bridge_task(
            session_id="session-b",
            conversation_id="conv-1",
            task_factory=_factory("session-b"),
        ),
    )

    assert {started_a, started_b} == {True, False}
    assert len(created_tasks) == 1
    owner_session = created_tasks[0][0]
    assert manager.bridge_tasks[owner_session]["conv-1"] is created_tasks[0][1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_start_bridge_task_allows_different_conversations() -> None:
    manager = ConnectionManager()
    manager.active_connections["session-a"] = object()  # type: ignore[assignment]
    manager.active_connections["session-b"] = object()  # type: ignore[assignment]
    manager.subscriptions["session-a"] = {"conv-1"}
    manager.subscriptions["session-b"] = {"conv-2"}
    task_conv_1 = _StubTask(done=False)
    task_conv_2 = _StubTask(done=False)

    started_conv_1 = await manager.try_start_bridge_task(
        session_id="session-a",
        conversation_id="conv-1",
        task_factory=_task_factory(task_conv_1),
    )
    started_conv_2 = await manager.try_start_bridge_task(
        session_id="session-b",
        conversation_id="conv-2",
        task_factory=_task_factory(task_conv_2),
    )

    assert started_conv_1 is True
    assert started_conv_2 is True
    assert manager.bridge_tasks["session-a"]["conv-1"] is task_conv_1
    assert manager.bridge_tasks["session-b"]["conv-2"] is task_conv_2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_start_bridge_task_requires_active_connection_and_subscription() -> None:
    manager = ConnectionManager()
    task = _StubTask(done=False)

    started_without_connection = await manager.try_start_bridge_task(
        session_id="session-a",
        conversation_id="conv-1",
        task_factory=_task_factory(task),
    )
    assert started_without_connection is False
    assert "session-a" not in manager.bridge_tasks

    manager.active_connections["session-a"] = object()  # type: ignore[assignment]
    started_without_subscription = await manager.try_start_bridge_task(
        session_id="session-a",
        conversation_id="conv-1",
        task_factory=_task_factory(task),
    )
    assert started_without_subscription is False
    assert "session-a" not in manager.bridge_tasks

    manager.subscriptions["session-a"] = {"conv-1"}
    started_with_subscription = await manager.try_start_bridge_task(
        session_id="session-a",
        conversation_id="conv-1",
        task_factory=_task_factory(task),
    )
    assert started_with_subscription is True
    assert manager.bridge_tasks["session-a"]["conv-1"] is task


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_start_bridge_task_replaces_stale_message_bridge() -> None:
    manager = ConnectionManager()
    manager.active_connections["session-new"] = object()  # type: ignore[assignment]
    manager.subscriptions["session-new"] = {"conv-1"}
    stale_task = _make_task_with_bridge_message_id("msg-old")
    manager.bridge_tasks["session-old"] = {"conv-1": stale_task}
    new_task = _StubTask(done=False)

    started = await manager.try_start_bridge_task(
        session_id="session-new",
        conversation_id="conv-1",
        bridge_message_id="msg-new",
        task_factory=_task_factory(new_task),
    )

    assert started is True
    assert stale_task.cancelled is True
    assert manager.bridge_tasks["session-new"]["conv-1"] is new_task


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_start_bridge_task_keeps_compatible_message_bridge() -> None:
    manager = ConnectionManager()
    manager.active_connections["session-new"] = object()  # type: ignore[assignment]
    manager.subscriptions["session-new"] = {"conv-1"}
    existing_task = _make_task_with_bridge_message_id("msg-1")
    manager.bridge_tasks["session-old"] = {"conv-1": existing_task}
    new_task = _StubTask(done=False)

    started = await manager.try_start_bridge_task(
        session_id="session-new",
        conversation_id="conv-1",
        bridge_message_id="msg-1",
        task_factory=_task_factory(new_task),
    )

    assert started is False
    assert existing_task.cancelled is False
    assert "session-new" not in manager.bridge_tasks


@pytest.mark.unit
def test_remove_conversation_subscriptions_is_idempotent_for_multiple_conversations() -> None:
    manager = ConnectionManager()
    manager.subscriptions["session-1"] = {"conv-1", "conv-2"}
    manager.conversation_subscribers["conv-1"] = {"session-1", "session-2"}
    manager.conversation_subscribers["conv-2"] = {"session-1"}

    manager._remove_conversation_subscriptions("session-1")
    manager._remove_conversation_subscriptions("session-1")

    assert "session-1" not in manager.subscriptions
    assert manager.conversation_subscribers["conv-1"] == {"session-2"}
    assert "conv-2" not in manager.conversation_subscribers


@pytest.mark.unit
def test_remove_project_subscriptions_is_idempotent_for_multiple_projects() -> None:
    manager = ConnectionManager()
    manager.session_project_subscriptions["session-1"] = {
        ("tenant-1", "project-1"),
        ("tenant-1", "project-2"),
    }
    manager.project_subscriptions["tenant-1"] = {
        "project-1": {"session-1", "session-2"},
        "project-2": {"session-1"},
    }

    manager._remove_project_subscriptions("session-1")
    manager._remove_project_subscriptions("session-1")

    assert "session-1" not in manager.session_project_subscriptions
    assert manager.project_subscriptions["tenant-1"]["project-1"] == {"session-2"}
    assert "project-2" not in manager.project_subscriptions["tenant-1"]
