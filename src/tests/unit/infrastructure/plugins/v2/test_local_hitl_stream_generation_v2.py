"""Generation lease coverage for the process-local HITL stream consumer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.hitl.local_resume_consumer import LocalHITLResumeConsumer
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    agent_worker_redis_runtime_factory_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    current_generation_v2,
    current_operation_context_v2,
    pin_generation_v2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedRedisClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_calls = 0
        self.closed = asyncio.Event()
        self.xgroup_create = AsyncMock()
        self.xack = AsyncMock()
        self.xadd = AsyncMock(return_value="1-0")

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str | bytes]:
        for key in ():
            yield key

    async def delete(self, *keys: str | bytes) -> int:
        return 0

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closed.set()


async def test_local_hitl_project_registration_holds_current_generation_redis_lease() -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=601,
        version=601,
    )
    assert first.accepted is True

    async def register_group(*_args: object, **_kwargs: object) -> None:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=602,
            version=602,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

    first_client.xgroup_create.side_effect = register_group
    consumer = LocalHITLResumeConsumer(generation_host=host)
    try:
        await consumer.add_project("tenant-1", "project-1")
        assert first_client.xgroup_create.await_count == 1
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        await consumer.stop()
        await host.close()

    assert second_client.close_calls == 1


async def test_local_hitl_resume_task_retains_exact_stream_generation_until_ack() -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=603,
        version=603,
    )
    assert first.accepted is True

    resume_started = asyncio.Event()
    allow_resume = asyncio.Event()

    async def resume_agent(*_args: object, **_kwargs: object) -> bool:
        resume_started.set()
        await allow_resume.wait()
        return True

    consumer = LocalHITLResumeConsumer(generation_host=host)
    consumer._resume_agent = AsyncMock(side_effect=resume_agent)
    try:
        async with pin_generation_v2(host):
            task = await consumer._schedule_resume_and_ack(
                "hitl:response:tenant-1:project-1",
                "1-0",
                "tenant-1",
                "project-1",
                "request-1",
                {"answer": "approved"},
                "conversation-1",
                "message-1",
            )

        await resume_started.wait()
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=604,
            version=604,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

        allow_resume.set()
        await task
        await asyncio.sleep(0)

        first_client.xack.assert_awaited_once_with(
            "hitl:response:tenant-1:project-1",
            consumer.CONSUMER_GROUP,
            "1-0",
        )
        assert second_client.xack.await_count == 0
        assert first_client.close_calls == 1
    finally:
        allow_resume.set()
        await consumer.stop()
        await host.close()


async def test_local_hitl_stop_releases_cancelled_resume_generation_reservation() -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=605,
        version=605,
    )
    assert first.accepted is True

    never_resume = asyncio.Event()

    async def resume_agent(*_args: object, **_kwargs: object) -> bool:
        await never_resume.wait()
        return True

    consumer = LocalHITLResumeConsumer(generation_host=host)
    consumer._resume_agent = AsyncMock(side_effect=resume_agent)
    try:
        async with pin_generation_v2(host):
            task = await consumer._schedule_resume_and_ack(
                "hitl:response:tenant-1:project-1",
                "2-0",
                "tenant-1",
                "project-1",
                "request-2",
                {"answer": "approved"},
                "conversation-2",
                "message-2",
            )

        await consumer.stop()
        assert task.cancelled() is True

        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=606,
            version=606,
        )
        assert second.accepted is True
        await asyncio.wait_for(first_client.closed.wait(), timeout=2)
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        never_resume.set()
        await consumer.stop()
        await host.close()


async def test_local_hitl_listener_does_not_inherit_starting_request_context() -> None:
    client = _TrackedRedisClient("current")

    async def redis_factory() -> _TrackedRedisClient:
        return client

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=607,
        version=607,
    )
    assert publication.accepted is True

    observed: dict[str, str] = {}
    listener_started = asyncio.Event()
    allow_listener_exit = asyncio.Event()

    async def inspect_listener_context() -> None:
        for name, accessor in (
            ("generation", current_generation_v2),
            ("operation", current_operation_context_v2),
        ):
            try:
                _ = accessor()
            except RuntimeV2Error as error:
                observed[name] = error.code
            else:
                observed[name] = "inherited"
        listener_started.set()
        await allow_listener_exit.wait()

    consumer = LocalHITLResumeConsumer(generation_host=host)
    consumer._listen_loop = inspect_listener_context
    try:
        async with pin_operation_context_v2(
            host,
            operation_id="request-that-starts-listener",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            await consumer.start()
            await listener_started.wait()

        assert observed == {
            "generation": "generation_not_pinned",
            "operation": "operation_context_not_pinned",
        }
    finally:
        allow_listener_exit.set()
        await consumer.stop()
        await host.close()


def test_local_hitl_stream_has_no_process_global_redis_pool_fallback() -> None:
    source = (_ROOT / "src/infrastructure/agent/hitl/local_resume_consumer.py").read_text(
        encoding="utf-8"
    )
    assert "agent_worker_state import" not in source
    assert "get_redis_client" not in source
    assert "self._redis =" not in source


def test_agent_worker_redis_factory_remains_the_data_plane_default() -> None:
    assert callable(agent_worker_redis_runtime_factory_v2)
