"""Pinned Redis authority coverage for workspace Todo event publication."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.tools.todo_tools import _publish_workspace_task_events_v2
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

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str | bytes]:
        for key in ():
            yield key

    async def xadd(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("Redis stream publication is outside this authority fixture")

    async def delete(self, *keys: str | bytes) -> int:
        return 0

    async def aclose(self) -> None:
        self.close_calls += 1


async def test_todo_event_publication_uses_exact_operation_redis_during_reload(
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
        generation=701,
        version=701,
    )
    assert first.accepted is True

    observed_clients: list[object] = []

    class Publisher:
        def __init__(self, redis_client: object) -> None:
            observed_clients.append(redis_client)

        async def publish_pending_events(self, events: object) -> None:
            assert tuple(events) == ()
            second = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=702,
                version=702,
            )
            assert second.accepted is True
            assert first_client.close_calls == 0

    monkeypatch.setattr(
        "src.application.services.workspace_task_event_publisher.WorkspaceTaskEventPublisher",
        Publisher,
    )

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="todo-event-publication",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            await _publish_workspace_task_events_v2(())

        assert observed_clients == [first_client]
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        await host.close()

    assert second_client.close_calls == 1


def test_todo_tools_do_not_read_the_process_global_redis_pool() -> None:
    source = (_ROOT / "src/infrastructure/agent/tools/todo_tools.py").read_text(encoding="utf-8")
    assert "agent_worker_state import" not in source
    assert "get_redis_client" not in source
