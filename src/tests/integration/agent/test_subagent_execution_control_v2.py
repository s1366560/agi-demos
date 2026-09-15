"""Actual PostgreSQL receipts, Redis delivery and live execution-owner cancellation."""

import asyncio
from types import SimpleNamespace

import pytest
from redis.asyncio import Redis

from src.configuration.config import get_settings
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.subagent.async_run_registry_v2 import (
    AsyncSubAgentRunRegistryV2,
    registry_call_v2,
)
from src.infrastructure.agent.subagent.control_channel import RedisControlChannel
from src.infrastructure.agent.subagent.execution_control_v2 import request_execution_control_v2
from src.infrastructure.agent.subagent.owner_control_v2 import SubAgentOwnerControlV2
from src.infrastructure.agent.subagent.run_reservation_v2 import reserve_session_run_v2
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    RedisAgentSubAgentControlServiceV2,
)
from src.tests.integration.agent import test_subagent_registry_postgres_v2 as fixtures

postgres_registry = fixtures.postgres_registry
pytestmark = pytest.mark.integration


async def _running_owner(registry, scope, run, channel, ready, owner_cancelled):
    async with registry.own_execution(scope.session_id, run.run_id):
        try:
            async with SubAgentOwnerControlV2(
                lambda: registry, scope.session_id, run.run_id, channel
            ):
                ready.set()
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            await registry_call_v2(
                registry,
                "mark_cancelled",
                scope.session_id,
                run.run_id,
                reason="owner acknowledged",
            )
            owner_cancelled.set()


async def test_pg_restart_replay_redis_steer_context_and_actual_owner_cancel(postgres_registry):
    _, sessions, scope = postgres_registry
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await reserve_session_run_v2(
        registry,
        conversation_id=scope.session_id,
        subagent_name="worker",
        task="test only",
        metadata={"parent_run_id": "already-completed-parent"},
        requester_session_key="parent",
        max_active_runs=2,
        max_children_per_requester=2,
        max_active_runs_per_lineage=2,
    )
    assert not isinstance(run, str)
    redis = Redis.from_url(get_settings().redis_url)
    channel = RedisControlChannel(redis)
    service = RedisAgentSubAgentControlServiceV2(
        redis_runtime=SimpleNamespace(client=redis), ttl_seconds=600
    )
    ready = asyncio.Event()
    owner_cancelled = asyncio.Event()

    task = asyncio.create_task(_running_owner(registry, scope, run, channel, ready, owner_cancelled))
    try:
        await asyncio.wait_for(ready.wait(), 5)
        args = {
            "conversation_id": scope.session_id,
            "run_id": run.run_id,
            "requested_by": "user",
            "action": "steer",
            "expected_control_revision": 0,
            "idempotency_key": "steer-once",
            "instruction": "ACTUAL_CHILD_STEERING_CONTEXT",
        }
        async def lose_delivery_response(**kwargs):
            await service.request_steer(**kwargs)
            raise RuntimeError("simulated lost delivery acknowledgement")

        uncertain_service = SimpleNamespace(request_steer=lose_delivery_response)
        with pytest.raises(RuntimeError, match="lost delivery"):
            await request_execution_control_v2(registry, uncertain_service, **args)
        result = await request_execution_control_v2(registry, service, **args)
        assert result["accepted"] is True
        restarted = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
        assert (await request_execution_control_v2(restarted, service, **args))["duplicate"] is True
        processor = SessionProcessor(
            config=ProcessorConfig(model="fixture", run_id=run.run_id, control_channel=channel),
            tools=[],
        )
        messages = []
        events = await processor._check_control_channel(messages)
        assert len(messages) == 1
        assert "ACTUAL_CHILD_STEERING_CONTEXT" in messages[0]["content"]
        assert events[0].run_id == run.run_id
        assert events[0].conversation_id == scope.session_id
        assert await processor._check_control_channel(messages) == []
        assert await channel.consume_control("unrelated-sibling") == []
        result = await request_execution_control_v2(
            restarted,
            service,
            conversation_id=scope.session_id,
            run_id=run.run_id,
            requested_by="user",
            action="kill_run",
            expected_control_revision=1,
            idempotency_key="kill-once",
            instruction=None,
        )
        assert result["accepted"] is True
        await asyncio.wait_for(owner_cancelled.wait(), 5)
        await task
        assert (
            await registry_call_v2(restarted, "get_run", scope.session_id, run.run_id)
        ).status.value == "cancelled"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await channel.cleanup(run.run_id)
        await redis.delete(f"subagent:cancel:{run.run_id}")
        await redis.aclose()
