"""Production HTTP control service must stop an actual leased task, then acknowledge."""

import asyncio

import pytest
from redis.asyncio import Redis

from src.configuration.config import get_settings
from src.infrastructure.agent.subagent.async_run_registry_v2 import registry_call_v2
from src.infrastructure.agent.subagent.control_channel import RedisControlChannel
from src.infrastructure.agent.subagent.owner_control_v2 import SubAgentOwnerControlV2
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    RedisAgentSubAgentControlServiceV2,
)
from src.infrastructure.plugins.v2.redis_runtime import RedisRuntimeServiceV2
from src.tests.integration.agent import test_subagent_registry_postgres_v2 as fixtures
from src.tests.integration.agent.test_subagent_owner_lease_v2 import _reserved

postgres_registry = fixtures.postgres_registry
pytestmark = pytest.mark.integration


async def test_http_control_service_stops_real_owner_and_persists_ack(postgres_registry):
    _, _, scope = postgres_registry
    registry, run = await _reserved(postgres_registry)
    redis = Redis.from_url(get_settings().redis_url)
    channel = RedisControlChannel(redis)
    entered = asyncio.Event()
    exited = asyncio.Event()

    async def owner():
        async with (
            registry.own_execution(scope.session_id, run.run_id),
            SubAgentOwnerControlV2(lambda: registry, scope.session_id, run.run_id, channel),
        ):
            try:
                entered.set()
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                exited.set()
                await registry_call_v2(
                    registry,
                    "mark_cancelled",
                    scope.session_id,
                    run.run_id,
                    reason="owner acknowledged",
                )
                raise

    task = asyncio.create_task(owner())
    try:
        await entered.wait()
        service = RedisAgentSubAgentControlServiceV2(
            redis_runtime=RedisRuntimeServiceV2(client=redis), ttl_seconds=600
        )
        await service.request_cancel(
            execution_id=run.run_id,
            requested_by="user",
            reason="test",
            conversation_id=scope.session_id,
        )
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done and exited.is_set(), "HTTP control did not reach the execution owner"
        result = await registry_call_v2(registry, "get_run", scope.session_id, run.run_id)
        assert result.status.value == "cancelled"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await redis.delete(
            "subagent:cancel:" + run.run_id,
            "agent:control:kill:" + run.run_id,
            "agent:control:stream:" + run.run_id,
        )
        await redis.aclose()
