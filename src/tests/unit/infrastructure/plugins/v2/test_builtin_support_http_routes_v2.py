"""Production V2 ownership tests for the support HTTP aliases."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2 import builtin_support_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.support_ticket_services import SupportTicketPageV2

pytestmark = pytest.mark.unit


def test_support_rows_are_complete_explicit_v2_contributions() -> None:
    definitions = subject.support_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        (method, f"{prefix}{path}")
        for prefix in ("/api/v1/support", "/support")
        for method, path in (
            ("POST", "/tickets"),
            ("GET", "/tickets"),
            ("GET", "/tickets/{ticket_id}"),
            ("PUT", "/tickets/{ticket_id}"),
            ("POST", "/tickets/{ticket_id}/close"),
        )
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SUPPORT_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "support",
        "support-2",
    }


def test_support_rows_preserve_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="support-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.support_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("support", "support-2")


async def test_generation_dispatcher_executes_both_support_aliases_before_static_fallback() -> None:
    services = SimpleNamespace(
        list_tickets=AsyncMock(
            return_value=SupportTicketPageV2(tickets=(), total=0, limit=25, offset=0)
        )
    )

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-a", is_superuser=False)

    async def support_application_override() -> object:
        return SimpleNamespace(services=services)

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.support_route_definitions_v2(),
        dependency_overrides={
            subject.get_current_user: current_user_override,
            subject.support_ticket_application_authority_dependency_v2: (
                support_application_override
            ),
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

    @outer.get("/support/tickets")
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="support-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        legacy_alias = await client.get("/support/tickets")
        api_alias = await client.get("/api/v1/support/tickets")

    expected = {"tickets": [], "total": 0, "limit": 25, "offset": 0, "has_more": False}
    assert legacy_alias.status_code == 200
    assert legacy_alias.json() == expected
    assert api_alias.status_code == 200
    assert api_alias.json() == expected
    assert services.list_tickets.await_count == 2
    await host.close()


def test_support_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_support_http_routes_definition_v2()

    assert definition.module_ref == subject.SUPPORT_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
