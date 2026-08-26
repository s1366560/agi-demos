"""Generation-owned SubAgent run-registry service and production cutover tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.subagent_run_registry_projection import (
    current_subagent_run_registry_v2,
)
from src.infrastructure.plugins.v2.subagent_run_registry_service import (
    SUBAGENT_RUN_REGISTRY_SERVICE_V2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_profile_provides_the_factory_registry_to_the_pinned_generation() -> None:
    registry = SubAgentRunRegistry()
    seen_config: dict[str, Any] = {}

    def factory(config: dict[str, Any]) -> SubAgentRunRegistry:
        seen_config.update(config)
        return registry

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(subagent_run_registry_factory=factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=181,
        version=181,
    )
    assert publication.accepted is True
    try:
        async with pin_generation_v2(host) as generation:
            projected = current_subagent_run_registry_v2()
            direct = generation.resolve(
                SUBAGENT_RUN_REGISTRY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )

            assert projected is registry
            assert projected is direct
            assert seen_config == {"strategy": "settings-shared"}
    finally:
        await host.close()
        registry.close()


def test_projection_fails_closed_without_a_pinned_generation() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        current_subagent_run_registry_v2()

    assert error.value.code == "generation_not_pinned"


async def test_invalid_factory_result_rejects_the_candidate_generation() -> None:
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            subagent_run_registry_factory=lambda _config: cast(SubAgentRunRegistry, object())
        )
    )

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=182,
        version=182,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert publication.receipt.error_message is not None
    assert "returned an invalid service" in publication.receipt.error_message
    await host.close()


async def test_failed_registry_candidate_preserves_the_last_good_generation() -> None:
    registry = SubAgentRunRegistry()
    calls = 0

    def factory(_config: dict[str, Any]) -> SubAgentRunRegistry:
        nonlocal calls
        calls += 1
        if calls == 1:
            return registry
        return cast(SubAgentRunRegistry, object())

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(subagent_run_registry_factory=factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=183,
        version=183,
    )
    second = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=184,
        version=184,
    )

    assert first.accepted is True
    assert second.accepted is False
    async with pin_generation_v2(host):
        assert current_subagent_run_registry_v2() is registry

    await host.close()
    registry.close()


def test_trace_production_path_and_top_level_di_have_no_static_registry_authority() -> None:
    source = (
        _ROOT / "src/infrastructure/adapters/primary/web/routers/agent/trace_router.py"
    ).read_text(encoding="utf-8")

    assert "current_subagent_run_registry_v2" in source
    assert "get_container_with_db" not in source
    assert ".subagent_run_registry()" not in source
    assert "subagent_run_registry" not in vars(DIContainer)
