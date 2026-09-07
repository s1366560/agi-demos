"""Lifecycle coverage for the process-shared background task manager."""

from __future__ import annotations

import asyncio

import pytest

from src.infrastructure.adapters.secondary import background_tasks as background_task_module
from src.infrastructure.adapters.secondary.background_tasks import TaskManager, TaskStatus

pytestmark = pytest.mark.unit


def test_module_does_not_expose_legacy_task_manager_singleton() -> None:
    assert "task_manager" not in vars(background_task_module)


async def test_cleanup_is_idempotent_and_close_disposes_running_tasks() -> None:
    manager = TaskManager()
    manager.start_cleanup()
    cleanup_task = manager._cleanup_task
    manager.start_cleanup()
    assert manager._cleanup_task is cleanup_task

    started = asyncio.Event()

    async def wait_forever() -> None:
        started.set()
        await asyncio.Event().wait()

    task_id = await manager.submit_task("wait", wait_forever)
    await started.wait()
    tracked = manager.get_task(task_id)
    assert tracked is not None
    assert tracked._task is not None
    assert not tracked._task.done()

    await manager.close()

    assert manager._cleanup_task is None
    assert tracked.status is TaskStatus.CANCELLED
    assert tracked._task.done()


async def test_close_without_started_effects_is_idempotent() -> None:
    manager = TaskManager()

    await manager.close()
    await manager.close()

    assert manager._cleanup_task is None
