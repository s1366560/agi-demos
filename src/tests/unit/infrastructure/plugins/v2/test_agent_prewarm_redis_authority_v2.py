"""Pinned Redis authority coverage for Agent session prewarming."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.state import agent_worker_state
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

    async def aclose(self) -> None:
        self.close_calls += 1


async def test_agent_prewarm_uses_exact_operation_redis_during_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    async def reject_process_global_redis() -> object:
        raise AssertionError("process-global Redis authority must not be used")

    tool_calls: list[dict[str, Any]] = []
    session_calls: list[dict[str, Any]] = []

    async def fake_provider_config() -> object:
        return object()

    async def fake_llm_client(provider_config: object) -> object:
        _ = provider_config
        return object()

    async def fake_tools(**kwargs: Any) -> list[object]:
        tool_calls.append(kwargs)
        return []

    async def fake_skills(**kwargs: Any) -> list[object]:
        _ = kwargs
        return []

    async def fake_agent_session(**kwargs: Any) -> object:
        session_calls.append(kwargs)
        return object()

    monkeypatch.setattr(agent_worker_state, "get_redis_client", reject_process_global_redis)
    monkeypatch.setattr(agent_worker_state, "get_or_create_provider_config", fake_provider_config)
    monkeypatch.setattr(agent_worker_state, "get_or_create_llm_client", fake_llm_client)
    monkeypatch.setattr(agent_worker_state, "get_or_create_tools", fake_tools)
    monkeypatch.setattr(agent_worker_state, "get_or_create_skills", fake_skills)
    monkeypatch.setattr(agent_worker_state, "get_or_create_agent_session", fake_agent_session)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=751,
        version=751,
    )
    assert first.accepted is True

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="agent-session-prewarm",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            second = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=752,
                version=752,
            )
            assert second.accepted is True
            assert first_client.close_calls == 0

            await agent_worker_state.prewarm_agent_session(
                tenant_id="tenant-a",
                project_id="project-a",
            )

        assert len(tool_calls) == 1
        assert tool_calls[0]["redis_client"] is first_client
        assert len(session_calls) == 1
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        await host.close()

    assert second_client.close_calls == 1


def test_agent_prewarm_does_not_read_process_global_redis_pool() -> None:
    source = inspect.getsource(agent_worker_state.prewarm_agent_session)
    assert "get_redis_client" not in source
