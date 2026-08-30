"""Pinned Redis authority coverage for workspace worker launch state."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.workspace import worker_launch
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    current_agent_worker_redis_client_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
    current_operation_context_v2,
    pin_operation_context_v2,
)
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

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str]:
        _ = (match, count)
        if False:
            yield "unused"

    async def delete(self, *_keys: str) -> int:
        return 0

    async def xadd(self, *_args: object, **_kwargs: object) -> str:
        return "stream-entry-1"

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


async def test_detached_worker_runs_in_exact_child_operation_during_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        generation=733,
        version=733,
    )
    assert first.accepted is True

    started = asyncio.Event()
    continue_launch = asyncio.Event()
    resolved: list[tuple[str, ScopeV2, object, object, object, object]] = []

    async def fake_launch(**_kwargs: object) -> dict[str, object]:
        started.set()
        operation = current_operation_context_v2()
        resolved.append(
            (
                operation.operation_id,
                operation.context.scope,
                current_generation_v2(),
                current_agent_worker_redis_client_v2(),
                operation.require(OPERATION_IDENTITY_SERVICE_V2),
                operation.require(OPERATION_METADATA_SERVICE_V2),
            )
        )
        await continue_launch.wait()
        return {"launched": True}

    monkeypatch.setattr(worker_launch, "launch_worker_session", fake_launch)
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="leader-conversation-a",
    )
    identity = {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "user_id": "user-a",
    }
    before = set(worker_launch._background_tasks)
    scheduled: tuple[asyncio.Task[object], ...] = ()
    try:
        async with pin_operation_context_v2(
            host,
            operation_id="leader-agent-turn",
            scope=scope,
            services={OPERATION_IDENTITY_SERVICE_V2: identity},
        ):
            await worker_launch.schedule_worker_session(
                workspace_id="workspace-a",
                task=MagicMock(id="task-a"),
                worker_agent_id="worker-a",
                actor_user_id="user-a",
                attempt_id="attempt-a",
            )
            scheduled = tuple(set(worker_launch._background_tasks) - before)
            assert len(scheduled) == 1
            await started.wait()

        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=734,
            version=734,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

        continue_launch.set()
        await scheduled[0]
        await asyncio.sleep(0)

        assert len(resolved) == 1
        operation_id, operation_scope, generation, redis_client, child_identity, metadata = (
            resolved[0]
        )
        assert operation_id == "workspace-worker-launch:task-a"
        assert operation_scope == scope
        assert child_identity == identity
        assert generation.descriptor.generation == 733
        assert redis_client is first_client
        assert metadata == {
            "kind": "workspace-worker-launch",
            "workspace_id": "workspace-a",
            "task_id": "task-a",
            "worker_agent_id": "worker-a",
            "attempt_id": "attempt-a",
            "parent_operation_id": "leader-agent-turn",
        }
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        continue_launch.set()
        if scheduled:
            await asyncio.gather(*scheduled, return_exceptions=True)
        await host.close()

    assert second_client.close_calls == 1


def test_worker_launch_does_not_read_process_global_redis_pool() -> None:
    source = (_ROOT / "src/infrastructure/agent/workspace/worker_launch.py").read_text(
        encoding="utf-8"
    )
    assert "agent_worker_state import" not in source
    assert "get_redis_client" not in source
