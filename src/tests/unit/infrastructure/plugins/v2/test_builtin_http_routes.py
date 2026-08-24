"""V2-only builtin route graph tests."""

from __future__ import annotations

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
from src.infrastructure.plugins.v2 import builtin_system_http_routes as system_subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    RouteTableRegistryV2,
    WebSocketRouteDefinitionV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_graph_without_v2_contributions_has_no_business_routes() -> None:
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )

    assert graph.mounted_row_ids == ()
    assert graph.static_mounted_row_ids == ()
    assert graph.v2_owned_row_ids == ()
    assert graph.route_signatures == ()


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
def test_graph_mounts_one_declared_mixed_http_websocket_row() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="mixed-tunnel-row",
        generation=1,
        digest="0" * 64,
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

    assert claimed.route_signatures == (
        ("/api/v1/tunnel/connect", "tunnel_connect", ()),
        ("/api/v1/admin/tunnel/status", "tunnel_status", ("GET",)),
    )
    assert "/api/v1/admin/tunnel/status" in claimed.table.openapi_snapshot(descriptor).schema["paths"]
    assert claimed.v2_owned_row_ids == ("tunnel",)
    assert claimed.static_mounted_row_ids == ()


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

    async def preview(path: str) -> dict[str, str]:
        return {"path": path, "source": "preview"}

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=(
            RouteDefinitionV2(
                owner_entry_id="preview-route",
                path="/{path:path}",
                methods=("GET",),
                endpoint=preview,
                name="preview-route",
            ),
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
def test_declared_builtin_row_has_no_static_handlers() -> None:
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=system_subject.system_route_definitions_v2(),
    )

    expected = system_subject.system_route_definitions_v2()

    assert claimed.table.definitions == expected
    assert len(claimed.route_signatures) == len(expected)
    assert claimed.mounted_row_ids == ("system",)
    assert claimed.v2_owned_row_ids == ("system",)
    assert claimed.static_mounted_row_ids == ()


@pytest.mark.unit
def test_required_row_without_a_v2_contribution_is_rejected_before_mount() -> None:
    with pytest.raises(RuntimeV2Error) as exc_info:
        build_builtin_route_graph_v2(
            workspace_core_settings=get_workspace_core_settings(),
            required_v2_row_ids={"system"},
        )

    assert exc_info.value.code == "required_route_contribution_missing"


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
