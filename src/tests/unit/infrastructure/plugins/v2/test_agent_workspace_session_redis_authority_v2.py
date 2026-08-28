"""Pinned Redis authority coverage for workspace session cache invalidation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.workspace.session_conversations import (
    _invalidate_conversation_list_cache,
)
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
        self.patterns: list[str] = []
        self.deleted: list[tuple[str, ...]] = []
        self.on_first_keys: Callable[[], Awaitable[None]] | None = None

    async def keys(self, pattern: str) -> list[str]:
        self.patterns.append(pattern)
        callback = self.on_first_keys
        self.on_first_keys = None
        if callback is not None:
            await callback()
        return [f"{pattern}cached"]

    async def delete(self, *keys: str) -> None:
        self.deleted.append(keys)

    async def aclose(self) -> None:
        self.close_calls += 1


async def test_workspace_session_cache_uses_exact_operation_redis_during_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    async def reject_process_global_redis() -> object:
        raise AssertionError("process-global Redis authority must not be used")

    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
        reject_process_global_redis,
    )

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=711,
        version=711,
    )
    assert first.accepted is True

    async def reload_generation() -> None:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=712,
            version=712,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

    first_client.on_first_keys = reload_generation

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="workspace-session-cache",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            await _invalidate_conversation_list_cache("project-a")

        assert first_client.patterns == [
            "conv_list:project-a:*",
            "conv_count:project-a:*",
        ]
        assert first_client.deleted == [
            ("conv_list:project-a:*cached",),
            ("conv_count:project-a:*cached",),
        ]
        assert second_client.patterns == []
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        await host.close()

    assert second_client.close_calls == 1


def test_workspace_session_cache_does_not_read_process_global_redis_pool() -> None:
    source = (_ROOT / "src/infrastructure/agent/workspace/session_conversations.py").read_text(
        encoding="utf-8"
    )
    assert "agent_worker_state import" not in source
    assert "get_redis_client" not in source
