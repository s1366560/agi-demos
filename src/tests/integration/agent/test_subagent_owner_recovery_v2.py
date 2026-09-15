"""Regression evidence for detached ownership across independently connected workers."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.core.detached_subagent_task_supervisor import (
    DetachedSubAgentTaskSupervisor,
)
from src.infrastructure.agent.subagent.async_run_registry_v2 import (
    AsyncSubAgentRunRegistryV2,
    registry_call_v2,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.subagent_sessions import make_session_tool_defs
from src.tests.integration.agent import test_subagent_registry_postgres_v2 as postgres_tests

postgres_registry = postgres_tests.postgres_registry

pytestmark = pytest.mark.integration


def _tools(registry, scope, supervisor, channel=None):
    async def cancel(run_id):
        return supervisor.cancel(run_id)

    return {
        tool.name: tool._tool_instance
        for tool in make_session_tool_defs(
            run_registry=registry,
            control_channel=channel,
            conversation_id=scope.session_id,
            requester_session_key="parent",
            visibility_default="self",
            observability_stats_provider=None,
            subagent_names=["worker"],
            subagent_descriptions={"worker": "test"},
            spawn_callback=AsyncMock(),
            cancel_callback=cancel,
            max_active_runs=1,
            max_active_runs_per_lineage=1,
            max_children_per_requester=1,
            delegation_depth=0,
            max_delegation_depth=2,
        )
    }


def _context(scope):
    return ToolContext(
        session_id="parent",
        message_id="message",
        call_id="call",
        agent_name="parent",
        conversation_id=scope.session_id,
    )


async def test_remote_kill_must_not_report_terminal_while_owner_still_runs(postgres_registry):
    _, sessions, scope = postgres_registry
    owner = DetachedSubAgentTaskSupervisor()
    remote = DetachedSubAgentTaskSupervisor()
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await registry_call_v2(
        registry, "create_run", scope.session_id, "worker", "task", requester_session_key="parent"
    )
    await registry_call_v2(registry, "mark_running", scope.session_id, run.run_id)
    alive = asyncio.Event()

    async def executing():
        alive.set()
        await asyncio.Event().wait()

    task = owner.create_task(run_id=run.run_id, coroutine=executing(), name="test-real-owner")
    try:
        await alive.wait()
        tools = _tools(
            AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope), scope, remote
        )
        result = await tools["subagents"].execute(_context(scope), action="kill", run_id=run.run_id)
        restored = await registry_call_v2(registry, "get_run", scope.session_id, run.run_id)
        # A cancel intent may be accepted; actual completion requires owner acknowledgement.
        assert task.done() or restored.status.value == "running", result.output
    finally:
        await owner.shutdown()
        await remote.shutdown()


async def test_new_worker_wait_repeatedly_times_out_without_reconciling_owner(postgres_registry):
    _, sessions, scope = postgres_registry
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await registry_call_v2(
        registry, "create_run", scope.session_id, "worker", "task", requester_session_key="parent"
    )
    await registry_call_v2(registry, "mark_running", scope.session_id, run.run_id)
    fresh_supervisor = DetachedSubAgentTaskSupervisor()
    tools = _tools(
        AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope), scope, fresh_supervisor
    )
    for _ in range(2):
        result = await tools["sessions_wait"].execute(
            _context(scope), run_id=run.run_id, timeout_seconds=0
        )
        state = json.loads(result.output)
        assert state["timed_out"] is True
        assert state["is_terminal"] is False
        assert state["run"]["status"] == "running"
        assert fresh_supervisor.task_for(run.run_id) is None


async def test_remote_durable_request_and_redis_stop_actual_owner_before_ack(postgres_registry):
    from redis.asyncio import Redis

    from src.configuration.config import get_settings
    from src.infrastructure.agent.subagent.control_channel import RedisControlChannel
    from src.infrastructure.agent.subagent.owner_control_v2 import SubAgentOwnerControlV2

    _, sessions, scope = postgres_registry
    redis = Redis.from_url(get_settings().redis_url)
    channel = RedisControlChannel(redis)
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await registry_call_v2(
        registry, "create_run", scope.session_id, "worker", "task", requester_session_key="parent"
    )
    await registry_call_v2(registry, "mark_running", scope.session_id, run.run_id)
    owner = DetachedSubAgentTaskSupervisor()
    remote = DetachedSubAgentTaskSupervisor()
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def executing():
        async with SubAgentOwnerControlV2(lambda: registry, scope.session_id, run.run_id, channel):
            try:
                entered.set()
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopped.set()
                await registry_call_v2(
                    registry,
                    "mark_cancelled",
                    scope.session_id,
                    run.run_id,
                    reason="owner acknowledged",
                )
                raise

    task = owner.create_task(run_id=run.run_id, coroutine=executing(), name="test-controlled-owner")
    try:
        await entered.wait()
        tools = _tools(
            AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope),
            scope,
            remote,
            channel,
        )
        result = await tools["subagents"].execute(_context(scope), action="kill", run_id=run.run_id)
        assert not result.is_error
        await asyncio.wait_for(stopped.wait(), timeout=2)
        await asyncio.gather(task, return_exceptions=True)
        restored = await registry_call_v2(registry, "get_run", scope.session_id, run.run_id)
        assert restored.status.value == "cancelled"
        assert restored.metadata["cancel_requested"] is True
        assert task.done()
        assert await channel.check_control(run.run_id) is None
    finally:
        await owner.shutdown()
        await remote.shutdown()
        await channel.cleanup(run.run_id)
        await redis.aclose()
