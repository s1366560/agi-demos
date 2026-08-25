"""Production V2 ownership tests for the builtin system HTTP row."""

from __future__ import annotations

from inspect import signature
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers import system as system_routes
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2 import builtin_system_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_system_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.system_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/system/features"),
        ("GET", "/api/v1/system/info"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SYSTEM_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"system"}


@pytest.mark.unit
def test_system_row_registers_generation_owned_handlers_without_wrappers() -> None:
    endpoints = {
        definition.name: definition.endpoint for definition in subject.system_route_definitions_v2()
    }

    assert endpoints == {
        "list_features": system_routes.list_features,
        "get_system_info": system_routes.get_system_info,
    }
    for endpoint in endpoints.values():
        current_user = signature(endpoint).parameters["_current_user"]
        assert current_user.default.dependency is system_routes.get_current_user


@pytest.mark.unit
def test_system_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="system-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.system_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            () if definition.methods == ("WEBSOCKET",) else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("system",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_system_handler_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    features = [{"name": "v2", "enabled": True}]
    gate = SimpleNamespace(get_enabled_features=lambda: features)
    monkeypatch.setattr(system_routes, "get_feature_gate", lambda: gate)

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-1")

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.system_route_definitions_v2(),
        dependency_overrides={
            system_routes.get_current_user: current_user_override,
        },
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
    path = "/api/v1/system/features"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="system-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == features
    await host.close()


@pytest.mark.unit
def test_system_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_system_http_routes_definition_v2()

    assert definition.module_ref == subject.SYSTEM_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
