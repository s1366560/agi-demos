"""V2-only Redis authority coverage for Agent data planes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_orchestration_runtime import (
    AGENT_ORCHESTRATION_RUNTIME_MODULE_V2,
)
from src.infrastructure.plugins.v2.agent_worker_runtime import AGENT_WORKER_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.redis_runtime import (
    REDIS_RUNTIME_SERVICE_V2,
    RedisRuntimeServiceV2,
)
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


def _redis_runtime(host: PlatformPluginRuntimeHostV2) -> RedisRuntimeServiceV2:
    generation = host.manager.current
    assert generation is not None
    runtime = generation.resolve(
        REDIS_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(runtime, RedisRuntimeServiceV2)
    return runtime


async def test_agent_redis_factory_pins_exact_generation_and_disposes_owned_clients() -> None:
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
        generation=401,
        version=401,
    )
    assert first.accepted is True

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="agent-redis:first",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as first_operation:
            first_runtime = first_operation.require(REDIS_RUNTIME_SERVICE_V2)
            assert isinstance(first_runtime, RedisRuntimeServiceV2)
            assert first_runtime.client is first_client

            second = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=402,
                version=402,
            )
            assert second.accepted is True
            assert first_runtime.client is first_client
            assert first_client.close_calls == 0

            async with pin_operation_context_v2(
                host,
                operation_id="agent-redis:second",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as second_operation:
                second_runtime = second_operation.require(REDIS_RUNTIME_SERVICE_V2)
                assert isinstance(second_runtime, RedisRuntimeServiceV2)
                assert second_runtime.client is second_client

            assert second_client.close_calls == 0

        assert first_client.close_calls == 1
    finally:
        await host.close()

    assert second_client.close_calls == 1


async def test_agent_redis_failed_candidate_retains_last_good_client() -> None:
    first_client = _TrackedRedisClient("first")
    calls = 0

    async def redis_factory() -> _TrackedRedisClient:
        nonlocal calls
        calls += 1
        if calls == 1:
            return first_client
        raise RuntimeError("candidate redis unavailable")

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=403,
        version=403,
    )
    failed = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=404,
        version=404,
    )

    assert first.accepted is True
    assert failed.accepted is False
    assert _redis_runtime(host).client is first_client
    assert first_client.close_calls == 0

    await host.close()

    assert first_client.close_calls == 1


def test_agent_worker_and_orchestration_contracts_require_redis_alias() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    modules = {item["module_ref"]: item for item in manifest["modules"]}
    expected_requirement = {
        "alias": "redis",
        "service": REDIS_RUNTIME_SERVICE_V2,
        "version": "1.0.0",
    }
    for module_ref in (
        AGENT_ORCHESTRATION_RUNTIME_MODULE_V2,
        AGENT_WORKER_RUNTIME_MODULE_V2,
    ):
        assert expected_requirement in modules[module_ref]["contract"]["services"]["requires"]

    profile = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in profile.entries}
    assert entries[AGENT_ORCHESTRATION_RUNTIME_MODULE_V2].inject["redis"] == (
        REDIS_RUNTIME_SERVICE_V2
    )
    assert entries[AGENT_WORKER_RUNTIME_MODULE_V2].inject["redis"] == REDIS_RUNTIME_SERVICE_V2


def test_agent_data_planes_bind_generation_redis_factory_without_core_static_reads() -> None:
    expected_bindings = (
        "src/application/services/agent/runtime_bootstrapper.py",
        "src/infrastructure/agent/actor/local_chat_worker.py",
        "src/infrastructure/agent/actor/project_agent_actor.py",
        "src/infrastructure/agent/hitl/generation_recovery_v2.py",
    )
    for relative_path in expected_bindings:
        source = (_ROOT / relative_path).read_text(encoding="utf-8")
        assert "redis_runtime_factory=agent_worker_redis_runtime_factory_v2" in source

    for relative_path in (
        "src/infrastructure/agent/core/project_react_agent.py",
        "src/infrastructure/plugins/v2/agent_orchestration_runtime.py",
    ):
        source = (_ROOT / relative_path).read_text(encoding="utf-8")
        assert "agent_worker_state import get_redis_client" not in source
