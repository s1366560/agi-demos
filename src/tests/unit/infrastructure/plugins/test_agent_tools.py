from types import SimpleNamespace

import pytest

from src.infrastructure.plugins.agent_tools import (
    AgentToolSetService,
    LegacyToolBuildError,
    legacy_tool_descriptor,
)
from src.infrastructure.plugins.context import PluginScopeContext


@pytest.mark.unit
def test_service_publishes_pins_and_builds_generations() -> None:
    async def execute(**kwargs):
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
