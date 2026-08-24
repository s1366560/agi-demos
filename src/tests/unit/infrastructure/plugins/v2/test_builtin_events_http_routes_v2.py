"""Production V2 ownership tests for the events HTTP row."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.features import get_feature_gate
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2 import builtin_events_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import (
    RouteTableRegistryV2,
    install_route_definitions_v2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit


def test_events_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.event_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/events"),
        ("GET", "/api/v1/events/types"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.EVENTS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"events"}
    assert all(
        definition.dependencies == (subject.EVENTS_FEATURE_DEPENDENCY_V2,)
        for definition in definitions
    )


def test_events_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="events-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.event_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("events",)


async def test_generation_dispatcher_executes_events_v2_before_static_fallback() -> None:
    services = SimpleNamespace(
        list_events=AsyncMock(return_value=([], 0)),
        get_event_types=AsyncMock(return_value=[]),
    )

    async def selected_tenant_override() -> str:
        return "tenant-a"

    async def event_service_override() -> object:
        return services

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.event_route_definitions_v2(),
        dependency_overrides={
            subject.get_selected_event_tenant: selected_tenant_override,
            subject.get_event_service: event_service_override,
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
    path = "/api/v1/events"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="events-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(path)

    assert result.status_code == 200
    assert result.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}
    services.list_events.assert_awaited_once_with(
        tenant_id="tenant-a",
        event_type=None,
        date_from=None,
        date_to=None,
        page=1,
        page_size=20,
    )
    await host.close()


async def test_v2_event_routes_preserve_feature_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = get_feature_gate()
    monkeypatch.setitem(gate._overrides, "events", False)

    app = FastAPI()
    install_route_definitions_v2(app, subject.event_route_definitions_v2())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/events")

    assert response.status_code == 403
    assert response.json() == {"detail": "Feature is not available"}


def test_events_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_events_http_routes_definition_v2()

    assert definition.module_ref == subject.EVENTS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
