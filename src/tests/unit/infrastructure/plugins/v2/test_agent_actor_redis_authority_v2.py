"""Pinned V2 Redis authority coverage for Actor execution and HITL recovery."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.actor.execution import load_hitl_state_for_resume
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    current_agent_worker_redis_client_v2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
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

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str | bytes]:
        for key in ():
            yield key

    async def delete(self, *keys: str | bytes) -> int:
        return 0

    async def xadd(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("Redis stream publication is outside this authority fixture")

    async def aclose(self) -> None:
        self.close_calls += 1


async def test_current_actor_redis_requires_and_uses_exact_operation_generation() -> None:
    client = _TrackedRedisClient("current")

    async def redis_factory() -> _TrackedRedisClient:
        return client

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=501,
        version=501,
    )
    assert publication.accepted is True

    try:
        with pytest.raises(RuntimeV2Error) as error:
            current_agent_worker_redis_client_v2()
        assert error.value.code == "operation_context_not_pinned"

        async with pin_operation_context_v2(
            host,
            operation_id="actor-redis:current",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            assert current_agent_worker_redis_client_v2() is client
            assert client.close_calls == 0
    finally:
        await host.close()

    assert client.close_calls == 1


async def test_hitl_state_lookup_holds_current_generation_lease_during_reload() -> None:
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
        generation=502,
        version=502,
    )
    assert first.accepted is True

    async def load_state(store: object, request_id: str) -> None:
        assert request_id == "hitl-request"
        assert vars(store)["_redis"] is first_client
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=503,
            version=503,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0
        return None

    try:
        with patch(
            "src.infrastructure.agent.actor.execution._load_hitl_state",
            new=AsyncMock(side_effect=load_state),
        ):
            assert (
                await load_hitl_state_for_resume(
                    "hitl-request",
                    generation_host=host,
                )
                is None
            )

        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        await host.close()

    assert second_client.close_calls == 1


def test_actor_and_hitl_core_modules_do_not_read_the_process_global_redis_pool() -> None:
    for relative_path in (
        "src/infrastructure/agent/actor/execution.py",
        "src/infrastructure/agent/actor/state/running_state.py",
        "src/infrastructure/agent/hitl/ray_hitl_handler.py",
        "src/infrastructure/agent/hitl/state_store.py",
    ):
        source = (_ROOT / relative_path).read_text(encoding="utf-8")
        assert "agent_worker_state import get_redis_client" not in source
