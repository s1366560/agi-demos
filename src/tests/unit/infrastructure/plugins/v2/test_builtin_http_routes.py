"""Full builtin inventory shadow-graph parity tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.infrastructure.plugins.route_inventory import INVENTORY_PATH
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2

_ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.unit
def test_shadow_graph_replays_every_runtime_owned_inventory_row() -> None:
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    inventory = json.loads((_ROOT / INVENTORY_PATH).read_text(encoding="utf-8"))
    runtime_owned = [
        row["row_id"]
        for row in inventory["entries"]
        if row["kind"] == "include_router" or row["row_id"] != "http-route-capabilities"
    ]

    assert len(inventory["entries"]) == 72
    assert graph.mounted_row_ids == tuple(runtime_owned)
    assert len(graph.mounted_row_ids) == 71
    assert len(graph.route_signatures) == len(set(graph.route_signatures))
    assert "/api/v1/agent/ws" in {signature[0] for signature in graph.route_signatures}
    assert "/api/v1/auth/token" in {signature[0] for signature in graph.route_signatures}
    assert "/api/v1/platform-plugins/v2/distribution" in {
        signature[0] for signature in graph.route_signatures
    }
    assert any(methods for _path, _name, methods in graph.route_signatures)


@pytest.mark.unit
def test_shadow_graph_mounts_frozen_generation_route_contributions() -> None:
    route = RouteDefinitionV2(
        owner_entry_id="dynamic-route",
        path="/api/v2/dynamic",
        methods=("GET",),
        endpoint=lambda: {"dynamic": True},
        name="dynamic-route",
    )

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=(route,),
    )

    assert graph.table.definitions == (route,)
    assert ("/api/v2/dynamic", "dynamic-route", ("GET",)) in graph.route_signatures


@pytest.mark.unit
def test_generation_route_precedes_root_preview_catch_all() -> None:
    async def dynamic(tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id, "source": "generation"}

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=(
            RouteDefinitionV2(
                owner_entry_id="dynamic-route",
                path="/plugin-startup/{tenant_id}/hello",
                methods=("GET",),
                endpoint=dynamic,
                name="dynamic-route",
            ),
        ),
    )

    paths = [path for path, _name, _methods in graph.route_signatures]
    assert paths.index("/plugin-startup/{tenant_id}/hello") < paths.index("/{path:path}")
