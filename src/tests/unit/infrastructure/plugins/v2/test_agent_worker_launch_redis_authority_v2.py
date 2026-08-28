"""Pinned Redis authority coverage for workspace worker launch state."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.workspace import worker_launch
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedRedisClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_calls = 0
        self.set_calls: list[tuple[str, str, bool, int]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.exists_calls: list[str] = []
        self.reload_generation = None

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        self.set_calls.append((key, value, nx, ex))
        reload_generation = self.reload_generation
        self.reload_generation = None
        if reload_generation is not None:
            await reload_generation()
        return True

    async def expire(self, key: str, seconds: int) -> None:
        self.expire_calls.append((key, seconds))

    async def exists(self, key: str) -> bool:
        self.exists_calls.append(key)
        return key.startswith("agent:running:")

    async def aclose(self) -> None:
        self.close_calls += 1


async def test_worker_launch_state_uses_exact_operation_redis_during_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    async def reject_process_global_redis() -> object:
        raise AssertionError("process-global Redis authority must not be used")

    from src.infrastructure.agent.state import agent_worker_state

    monkeypatch.setattr(agent_worker_state, "get_redis_client", reject_process_global_redis)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=731,
        version=731,
    )
    assert first.accepted is True

    async def reload_generation() -> None:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=732,
            version=732,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

    first_client.reload_generation = reload_generation

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="workspace-worker-launch-state",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            assert await worker_launch._is_on_cooldown("conversation-a") is False
            await worker_launch._refresh_launch_cooldown("conversation-a")
            await worker_launch._refresh_worker_agent_running_marker(
                "conversation-a",
                "attempt-a",
            )

        assert first_client.set_calls == [
            (
                "workspace:worker_launch:cooldown:conversation-a",
                "1",
                True,
                worker_launch.WORKER_LAUNCH_COOLDOWN_SECONDS,
            )
        ]
        assert first_client.exists_calls == [
            "agent:finished:conversation-a",
            "agent:running:conversation-a",
        ]
        assert first_client.expire_calls == [
            (
                "workspace:worker_launch:cooldown:conversation-a",
                worker_launch.WORKER_LAUNCH_COOLDOWN_SECONDS,
            ),
            (
                "agent:running:conversation-a",
                worker_launch.WORKER_LAUNCH_COOLDOWN_SECONDS,
            ),
        ]
        assert second_client.set_calls == []
        assert second_client.expire_calls == []
        assert second_client.exists_calls == []
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        await host.close()

    assert second_client.close_calls == 1


def test_worker_launch_does_not_read_process_global_redis_pool() -> None:
    source = (_ROOT / "src/infrastructure/agent/workspace/worker_launch.py").read_text(
        encoding="utf-8"
    )
    assert "agent_worker_state import" not in source
    assert "get_redis_client" not in source
