"""Pinned Redis authority coverage for workspace contract-agent services."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    create_workspace_contract_agent_service,
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

    async def aclose(self) -> None:
        self.close_calls += 1


async def test_contract_agent_service_uses_exact_operation_redis_during_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    async def reject_process_global_redis() -> object:
        raise AssertionError("process-global Redis authority must not be used")

    observed_clients: list[object] = []
    agent_service = object()

    class FakeDIContainer:
        def __init__(self, *, db: object, redis_client: object) -> None:
            _ = db
            observed_clients.append(redis_client)

        def agent_service(self, llm: object) -> object:
            _ = llm
            return agent_service

    from src.configuration import di_container
    from src.infrastructure.adapters.primary.web.startup import container as startup_container
    from src.infrastructure.agent.state import agent_worker_state

    monkeypatch.setattr(startup_container, "get_app_container", lambda: None)
    monkeypatch.setattr(agent_worker_state, "get_redis_client", reject_process_global_redis)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=721,
        version=721,
    )
    assert first.accepted is True

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="workspace-contract-agent-service",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            second = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=722,
                version=722,
            )
            assert second.accepted is True
            assert first_client.close_calls == 0

            resolved = await create_workspace_contract_agent_service(
                db=object(),
                llm=object(),
            )

        assert resolved is agent_service
        assert observed_clients == [first_client]
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        await host.close()

    assert second_client.close_calls == 1


def test_contract_agent_runtime_does_not_read_process_global_redis_pool() -> None:
    source = (_ROOT / "src/infrastructure/agent/workspace/contract_agent_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "agent_worker_state import" not in source
    assert "get_redis_client" not in source
