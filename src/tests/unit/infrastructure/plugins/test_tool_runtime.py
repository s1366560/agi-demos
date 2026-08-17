import pytest

from src.domain.model.plugins import PluginGeneration
from src.domain.ports.plugins import ToolDescriptor
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.tool_runtime import (
    StaticToolProvider,
    ToolGenerationStore,
    ToolSelectionPolicy,
    ToolSetBuilder,
    ToolSetBuildError,
    cache_key,
)


async def echo(_arguments, _scope):
    return "ok"


def _descriptor(tool_id: str) -> ToolDescriptor:
    return ToolDescriptor(
        id=tool_id,
        name=tool_id,
        description=f"Test {tool_id}",
    )


@pytest.mark.unit
async def test_builder_rejects_duplicate_tool_ownership() -> None:
    first = StaticToolProvider("first", (_descriptor("shared"),), {"shared": echo})
    second = StaticToolProvider("second", (_descriptor("shared"),), {"shared": echo})

    with pytest.raises(ToolSetBuildError, match="provided by both first and second"):
        await ToolSetBuilder({"first": first, "second": second}).build(
            PluginScopeContext(tenant_id="tenant"),
            PluginGeneration("digest", 1),
        )


@pytest.mark.unit
async def test_generation_store_pins_previous_generation() -> None:
    provider = StaticToolProvider("provider", (_descriptor("tool"),), {"tool": echo})
    builder = ToolSetBuilder({"provider": provider})
    scope = PluginScopeContext(tenant_id="tenant", project_id="project")
    generation_one = await builder.build(scope, PluginGeneration("digest", 1))
    generation_two = await builder.build(scope, PluginGeneration("digest", 2))
    store = ToolGenerationStore()

    store.publish(generation_one)
    store.publish(generation_two)

    assert store.current() is generation_two
    assert store.pin(PluginGeneration("digest", 1), scope) is generation_one


@pytest.mark.unit
async def test_tool_implementation_comes_from_pinned_generation() -> None:
    provider = StaticToolProvider("provider", (_descriptor("tool"),), {"tool": echo})
    generation = await ToolSetBuilder({"provider": provider}).build(
        PluginScopeContext(tenant_id="tenant"),
        PluginGeneration("digest", 3),
    )

    implementation = await generation.build("tool")
    assert await implementation({}, generation.scope) == "ok"


@pytest.mark.unit
def test_selection_policy_applies_deterministic_budget() -> None:
    descriptors = {
        tool_id: ToolDescriptor(
            id=tool_id,
            name=tool_id,
            description=tool_id,
            tags=("filesystem",),
        )
        for tool_id in ["a", "b", "c"]
    }
    policy = ToolSelectionPolicy(
        included_tags=frozenset({"filesystem"}),
        excluded_tools=frozenset({"b"}),
        max_tools=1,
    )

    assert [item.id for item in policy.apply(descriptors)] == ["a"]


@pytest.mark.unit
def test_cache_key_contains_profile_scope_and_generation() -> None:
    scope = PluginScopeContext(tenant_id="tenant", project_id="project")
    assert cache_key("digest", scope, PluginGeneration("digest", 7)) == (
        "digest",
        ("tenant", "project", None),
        7,
    )
