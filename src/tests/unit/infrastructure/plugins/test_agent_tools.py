from types import SimpleNamespace
from typing import Any

import pytest

import src.infrastructure.agent.state.agent_worker_state as worker_state
from src.infrastructure.agent.state.agent_worker_state import get_cached_tools_for_project
from src.infrastructure.plugins.agent_tools import (
    AgentToolSetService,
    LegacyToolBuildError,
    legacy_tool_descriptor,
)
from src.infrastructure.plugins.context import PluginScopeContext


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


def _tool_settings(*, v2: bool, remove_legacy: bool) -> SimpleNamespace:
    return SimpleNamespace(
        platform_plugin_agent_tools_v2=v2,
        platform_plugin_agent_tools_remove_legacy=remove_legacy,
        platform_plugin_agent_tools_shadow=False,
        platform_plugin_agent_tools_shadow_percent=0,
        platform_plugin_shadow_scope_allowlist=None,
    )


@pytest.mark.unit
def test_tool_legacy_removal_requires_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_state._tools_cache.pop("project-remove", None)
    worker_state._tools_cache["project-remove"] = {"demo": SimpleNamespace(name="demo")}
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: _tool_settings(v2=False, remove_legacy=True),
    )

    with pytest.raises(ValueError, match="requires agent tools V2"):
        get_cached_tools_for_project("project-remove")


@pytest.mark.unit
def test_tool_legacy_removal_uses_scoped_generation_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = SimpleNamespace(
        name="demo",
        description="Demo",
        parameters={"type": "object"},
    )
    project_id = "project-remove-typed"
    worker_state._tools_cache[project_id] = {"demo": tool}
    service = AgentToolSetService(profile_digest="remove-legacy")
    service.publish(PluginScopeContext(project_id=project_id), {"demo": tool})
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: _tool_settings(v2=True, remove_legacy=True),
    )
    monkeypatch.setattr(
        "src.infrastructure.plugins.agent_tools.get_agent_tool_set_service",
        lambda: service,
    )

    assert get_cached_tools_for_project(project_id) == {"demo": tool}


@pytest.mark.unit
def test_tool_legacy_removal_fails_loud_without_scoped_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = "project-remove-missing"
    worker_state._tools_cache[project_id] = {
        "demo": SimpleNamespace(name="demo", description="Demo")
    }

    class MissingGenerationService:
        def shadow_comparison(
            self, scope: object, tools: dict[str, object]
        ) -> tuple[None, dict[str, object], bool]:
            return None, tools, True

        def publish(self, scope: object, tools: dict[str, object]) -> None:
            return None

        def current(self, scope: object) -> None:
            return None

    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: _tool_settings(v2=True, remove_legacy=True),
    )
    monkeypatch.setattr(
        "src.infrastructure.plugins.agent_tools.get_agent_tool_set_service",
        MissingGenerationService,
    )

    with pytest.raises(RuntimeError, match="legacy tool cache fallback is disabled"):
        get_cached_tools_for_project(project_id)
