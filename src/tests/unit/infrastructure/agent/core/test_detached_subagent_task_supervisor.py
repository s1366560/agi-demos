# pyright: reportPrivateUsage=false
"""Lifecycle tests for project-owned detached SubAgent task supervision."""

from __future__ import annotations

import asyncio
from contextvars import copy_context

import pytest

from src.infrastructure.agent.core.detached_subagent_task_supervisor import (
    DetachedSubAgentTaskSupervisor,
)
from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


async def _block_until_cancelled(
    *,
    started: asyncio.Event,
    cleaned: asyncio.Event,
) -> None:
    started.set()
    try:
        await asyncio.Event().wait()
    finally:
        await asyncio.sleep(0)
        cleaned.set()


async def test_shutdown_is_idempotent_cancels_and_awaits_all_tasks() -> None:
    supervisor = DetachedSubAgentTaskSupervisor()
    started = asyncio.Event()
    cleaned = asyncio.Event()
    task = supervisor.create_task(
        run_id="run-1",
        coroutine=_block_until_cancelled(started=started, cleaned=cleaned),
        name="detached-run-1",
        context=copy_context(),
    )
    await started.wait()

    await asyncio.gather(supervisor.shutdown(), supervisor.shutdown())

    assert supervisor.is_closed is True
    assert task.cancelled() is True
    assert cleaned.is_set() is True
    assert supervisor.tasks == {}


async def test_shutdown_closes_registration_gate_before_awaiting_cleanup() -> None:
    supervisor = DetachedSubAgentTaskSupervisor()
    started = asyncio.Event()
    cleaned = asyncio.Event()
    supervisor.create_task(
        run_id="run-active",
        coroutine=_block_until_cancelled(started=started, cleaned=cleaned),
        name="detached-run-active",
        context=copy_context(),
    )
    await started.wait()

    shutdown = asyncio.create_task(supervisor.shutdown())
    await asyncio.sleep(0)

    async def _rejected() -> None:
        await asyncio.sleep(0)

    with pytest.raises(RuntimeV2Error) as error:
        supervisor.create_task(
            run_id="run-too-late",
            coroutine=_rejected(),
            name="detached-run-too-late",
            context=copy_context(),
        )

    assert error.value.code == "detached_subagent_supervisor_closed"
    await shutdown
    assert cleaned.is_set() is True
    assert "run-too-late" not in supervisor.tasks


async def test_new_react_agent_can_cancel_task_started_by_previous_instance() -> None:
    supervisor = DetachedSubAgentTaskSupervisor()
    first = ReActAgent(
        model="test-model",
        tools={},
        detached_subagent_task_supervisor=supervisor,
    )
    second = ReActAgent(
        model="test-model",
        tools={},
        detached_subagent_task_supervisor=supervisor,
    )
    started = asyncio.Event()
    cleaned = asyncio.Event()
    task = supervisor.create_task(
        run_id="run-before-refresh",
        coroutine=_block_until_cancelled(started=started, cleaned=cleaned),
        name="detached-run-before-refresh",
        context=copy_context(),
    )
    await started.wait()

    assert "run-before-refresh" in first._subagent_session_tasks
    assert "run-before-refresh" in second._subagent_session_tasks
    assert await second._cancel_subagent_session("run-before-refresh") is True
    await asyncio.gather(task, return_exceptions=True)

    assert cleaned.is_set() is True
    assert "run-before-refresh" not in first._subagent_session_tasks
    assert "run-before-refresh" not in second._subagent_session_tasks
    await supervisor.shutdown()


def test_direct_react_agent_gets_a_private_default_supervisor() -> None:
    first = ReActAgent(model="test-model", tools={})
    second = ReActAgent(model="test-model", tools={})

    assert isinstance(first._detached_subagent_task_supervisor, DetachedSubAgentTaskSupervisor)
    assert first._detached_subagent_task_supervisor is not second._detached_subagent_task_supervisor
    assert not first._subagent_session_tasks
    assert not second._subagent_session_tasks
