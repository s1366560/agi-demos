"""Full builtin inventory shadow-graph parity tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers.tunnel import tunnel_connect, tunnel_status
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.route_inventory import INVENTORY_PATH
from src.infrastructure.plugins.route_loader import RouteLoadError
from src.infrastructure.plugins.v2 import builtin_system_http_routes as system_subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    RouteTableRegistryV2,
    WebSocketRouteDefinitionV2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

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
def test_shadow_graph_can_replace_one_complete_mixed_http_websocket_row() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="mixed-tunnel-row",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=(
            WebSocketRouteDefinitionV2(
                owner_entry_id="builtin-tunnel-routes",
                path="/api/v1/tunnel/connect",
                endpoint=tunnel_connect,
                name="tunnel_connect",
                replaces_builtin_row_id="tunnel",
            ),
            RouteDefinitionV2(
                owner_entry_id="builtin-tunnel-routes",
                path="/api/v1/admin/tunnel/status",
                methods=("GET",),
                endpoint=tunnel_status,
                name="tunnel_status",
                tags=("tunnel",),
                response_model=dict[str, object],
                replaces_builtin_row_id="tunnel",
            ),
        ),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("tunnel",)


@pytest.mark.unit
def test_shadow_graph_snapshots_outer_dependency_overrides() -> None:
    async def original_dependency() -> str:
        return "original"

    async def generation_override() -> str:
        return "generation"

    async def later_override() -> str:
        return "later"

    async def endpoint(value: str = Depends(original_dependency)) -> dict[str, str]:
        return {"value": value}

    overrides = {original_dependency: generation_override}
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=(
            RouteDefinitionV2(
                owner_entry_id="override-route",
                path="/api/v2/override",
                methods=("GET",),
                endpoint=endpoint,
                name="override-route",
            ),
        ),
        dependency_overrides=overrides,
    )
    overrides[original_dependency] = later_override

    request_host = FastAPI()
    request_host.mount("/", graph.table)
    with TestClient(request_host) as client:
        response = client.get("/api/v2/override")

    assert response.status_code == 200
    assert response.json() == {"value": "generation"}


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


@pytest.mark.unit
def test_complete_builtin_row_claim_replaces_static_handlers_in_place() -> None:
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )

    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=system_subject.system_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert claimed.mounted_row_ids == baseline.mounted_row_ids
    assert claimed.v2_owned_row_ids == ("system",)
    assert "system" not in claimed.static_mounted_row_ids
    assert len(claimed.static_mounted_row_ids) + len(claimed.v2_owned_row_ids) == len(
        claimed.mounted_row_ids
    )

@pytest.mark.unit
def test_partial_builtin_row_claim_is_rejected_before_mount() -> None:
    with pytest.raises(RouteLoadError, match="complete route key set"):
        build_builtin_route_graph_v2(
            workspace_core_settings=get_workspace_core_settings(),
            route_definitions=(
                RouteDefinitionV2(
                    owner_entry_id="builtin-system-routes",
                    path="/api/v1/system/features",
                    methods=("GET",),
                    endpoint=lambda: {"source": "v2"},
                    name="list_features",
                    replaces_builtin_row_id="system",
                ),
            ),
        )


@pytest.mark.unit
async def test_generation_dispatcher_executes_claimed_row_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def v2_features(_current_user: object) -> list[dict[str, str]]:
        return [{"source": "v2"}]

    monkeypatch.setattr(system_subject, "_list_features", v2_features)

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=system_subject.system_route_definitions_v2(),
        dependency_overrides={system_subject.get_current_user: lambda: object()},
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path="config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    distribution = host.current_distribution
    assert distribution is not None
    registry = RouteTableRegistryV2()
    await registry.publish(distribution.descriptor, graph.table)
    outer = FastAPI()
    outer.state.platform_plugin_route_registry_v2 = registry
    mount_generation_http_dispatcher_v2(outer)

    @outer.get("/api/v1/system/features")
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="builtin-system-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/api/v1/system/features")

    assert response.status_code == 200
    assert response.json() == [{"source": "v2"}]
    await host.close()
