"""Readiness reads the actual router task and Redis without processing business work."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from src.infrastructure.agent.actor.hitl_router_actor import HITLStreamRouterActor


@pytest.mark.unit
@pytest.mark.parametrize(
    "case",
    [
        "ready",
        "stopped",
        "no_listener",
        "exited",
        "cancelled",
        "no_redis",
        "disconnected",
        "false_ping",
        "timeout",
    ],
)
async def test_router_health_projects_actual_task_and_redis_state(case: str) -> None:
    inner = HITLStreamRouterActor.__ray_metadata__.modified_class
    actor = inner.__new__(inner)
    actor._running = case != "stopped"
    actor._listen_task = asyncio.create_task(asyncio.Event().wait())
    task = actor._listen_task
    actor._redis = AsyncMock()
    actor._redis.ping.return_value = True
    actor._ensure_redis = AsyncMock()
    if case == "no_listener":
        actor._listen_task = None
    elif case in {"exited", "cancelled"}:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if case == "exited":
            actor._listen_task = asyncio.create_task(asyncio.sleep(0))
            await actor._listen_task
    elif case == "no_redis":
        actor._redis = None
    elif case == "disconnected":
        actor._redis.ping.side_effect = RedisConnectionError("neutral secret must not escape")
    elif case == "false_ping":
        actor._redis.ping.return_value = False
    elif case == "timeout":
        actor._redis.ping.side_effect = TimeoutError
    try:
        result = await actor.health()
        assert result == {
            "running": case != "stopped",
            "listening": case not in {"no_listener", "exited", "cancelled"},
            "redis_connected": case not in {"no_redis", "disconnected", "false_ping", "timeout"},
            "ready": case == "ready",
        }
        actor._ensure_redis.assert_not_awaited()
        if actor._redis is not None:
            actor._redis.xreadgroup.assert_not_awaited()
            actor._redis.xack.assert_not_awaited()
            actor._redis.xadd.assert_not_awaited()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.unit
async def test_router_health_rechecks_listener_after_redis_ping() -> None:
    inner = HITLStreamRouterActor.__ray_metadata__.modified_class
    actor = inner.__new__(inner)
    actor._running = True
    task = asyncio.create_task(asyncio.Event().wait())
    actor._listen_task = task
    actor._redis = AsyncMock()

    async def ping() -> bool:
        actor._running = False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    actor._redis.ping.side_effect = ping
    result = await actor.health()
    assert result == {"running": False, "listening": False, "redis_connected": True, "ready": False}
