"""A pinned generation sees only its own published route table."""

from __future__ import annotations

import pytest

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    RouteTableRegistryV2,
    RouteTableV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


def _descriptor(generation: int) -> PluginGenerationDescriptorV2:
    return PluginGenerationDescriptorV2(
        profile_id="profile",
        generation=generation,
        digest="ab" * 32,
    )


def _table(value: str) -> RouteTableV2:
    async def endpoint() -> dict[str, str]:
        return {"generation": value}

    return RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="builtin-http",
                path="/api/value",
                methods=("GET",),
                endpoint=endpoint,
                name=f"value-{value}",
                tags=("Plugin V2",),
            ),
        )
    )


@pytest.mark.unit
def test_same_generation_table_is_found_and_other_generation_is_not_substituted() -> None:
    registry = RouteTableRegistryV2()
    current = registry.stage(_descriptor(1), _table("current"))
    registry.activate(current)
    same = registry.stage(_descriptor(2), _table("same"))
    assert registry.current is not None

    resolved = registry.resolve(_descriptor(2))
    assert resolved is same
    assert resolved.openapi.descriptor == _descriptor(2)
    assert resolved.descriptor != registry.current.descriptor

    with pytest.raises(RuntimeV2Error) as raised:
        registry.resolve(_descriptor(3))
    assert raised.value.code == "route_generation_unavailable"
    assert registry.current is current
