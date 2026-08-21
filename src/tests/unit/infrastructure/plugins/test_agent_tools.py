from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.infrastructure.agent.state.agent_worker_state as worker_state
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.state.agent_session_pool import generation_cache_key_v2
from src.infrastructure.agent.state.agent_worker_state import get_cached_tools_for_project
from src.infrastructure.plugins.agent_tools import (
    AgentToolSetService,
    LegacyToolBuildError,
    legacy_tool_descriptor,
)
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[5]
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


@pytest.fixture
async def generation_host() -> AsyncIterator[PlatformPluginRuntimeHostV2]:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="agent-tool-test-generation-1",
    )
    try:
        yield host
    finally:
        await host.close()


@pytest.fixture(autouse=True)
def _clear_worker_tool_cache() -> None:
    worker_state._tools_cache.clear()
    yield
    worker_state._tools_cache.clear()


@pytest.mark.unit
def test_service_publishes_pins_and_builds_generations() -> None:
    async def execute(**kwargs: Any) -> Any:
        return kwargs["value"]

    tool = SimpleNamespace(
        name="demo",
        description="Demo tool",
        parameters={"type": "object"},
        execute=execute,
    )
    service = AgentToolSetService()
    scope = PluginScopeContext(tenant_id="tenant", project_id="project")
    first = service.publish(scope, {"demo": tool})
    second = service.publish(scope, {"demo": tool})

    pinned = service.pin(first.generation, scope)
    assert pinned is not None
    implementation = service.implementation("demo", pinned)
    import asyncio

    assert asyncio.run(implementation({"value": 42}, scope)) == 42
    assert service.current(scope) is not None
    assert service.current(scope) is service.current(scope)
    assert service.pin(first.generation, scope) is pinned
    assert second.generation.sequence > first.generation.sequence


@pytest.mark.unit
def test_legacy_tool_descriptor_rejects_name_drift() -> None:
    with pytest.raises(LegacyToolBuildError, match="cache key demo, advertised name other"):
        legacy_tool_descriptor("demo", SimpleNamespace(name="other"))


@pytest.mark.unit
async def test_worker_tool_reads_are_independent_of_legacy_scoped_service(
    monkeypatch: pytest.MonkeyPatch,
    generation_host: PlatformPluginRuntimeHostV2,
) -> None:
    tool = SimpleNamespace(
        name="demo",
        description="Demo",
        parameters={"type": "object"},
    )
    legacy_tool = SimpleNamespace(
        name="other",
        description="Legacy-only tool",
        parameters={"type": "object"},
    )
    project_id = "project-remove-typed"
    legacy_service = AgentToolSetService(profile_digest="legacy-scoped-read")
    legacy_service.publish(
        PluginScopeContext(project_id=project_id),
        {"other": legacy_tool},
    )
    monkeypatch.setattr(
        "src.infrastructure.plugins.agent_tools.get_agent_tool_set_service",
        lambda: legacy_service,
    )

    async with pin_operation_context_v2(
        generation_host,
        operation_id="typed-tool-read",
        scope=_ROOT_SCOPE,
    ) as operation:
        descriptor = operation.descriptor
        cache_key = generation_cache_key_v2(
            project_id,
            generation_descriptor=descriptor,
        )
        worker_state._tools_cache[cache_key] = {"demo": tool}
        assert get_cached_tools_for_project(project_id, descriptor) == {"demo": tool}
