"""Production V2 ownership tests for the builtin shares HTTP row."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers import shares as shares_router
from src.infrastructure.adapters.primary.web.shares_application_authority_v2 import (
    SharesApplicationAuthorityV2,
    public_shares_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2 import builtin_shares_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.shares_services import (
    SharedMemoryAccessV2,
    SharesApplicationServicesV2,
)


def test_shares_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.shares_route_definitions_v2()

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        ("/api/v1/memories/{memory_id}/shares", ("POST",), "create_share"),
        ("/api/v1/memories/{memory_id}/shares", ("GET",), "list_shares"),
        (
            "/api/v1/memories/{memory_id}/shares/{share_id}",
            ("DELETE",),
            "delete_share",
        ),
        ("/api/v1/shared/{share_token}", ("GET",), "get_shared_memory"),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SHARES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"shares"}


def test_shares_row_registers_production_handlers_without_forwarding_wrappers() -> None:
    definitions = subject.shares_route_definitions_v2()

    assert tuple(definition.endpoint for definition in definitions) == (
        shares_router.create_share,
        shares_router.list_shares,
        shares_router.delete_share,
        shares_router.get_shared_memory,
    )


def test_shares_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="shares-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.shares_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("shares",)


def test_shares_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_shares_http_routes_definition_v2()

    assert definition.module_ref == subject.SHARES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


@pytest.mark.unit
async def test_generation_dispatcher_executes_public_share_v2_before_static_fallback() -> None:
    calls: list[tuple[object, ...]] = []
    fallback_calls: list[str] = []
    response: dict[str, Any] = {
        "memory": {"id": "memory-1", "content": "generation-owned"},
        "share": {"permissions": {"view": True}},
    }

    class SharesService:
        async def get_shared_memory(self, *, share_token: str) -> SharedMemoryAccessV2:
            calls.append(("shares", share_token))
            return SharedMemoryAccessV2(
                payload=response,
                memory_id="memory-1",
                share_id="share-1",
            )

    authority = SharesApplicationAuthorityV2(
        operation=cast(Any, SimpleNamespace()),
        db=cast(AsyncSession, SimpleNamespace(commit=AsyncMock())),
        current_user=None,
        services=SharesApplicationServicesV2(shares=cast(Any, SharesService())),
    )

    async def authority_override() -> SharesApplicationAuthorityV2:
        calls.append(("authority", authority.current_user, authority.db))
        return authority

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.shares_route_definitions_v2(),
        dependency_overrides={
            public_shares_application_authority_dependency_v2: authority_override,
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

    @outer.get("/api/v1/shared/{share_token}")
    async def static_fallback(share_token: str) -> dict[str, str]:
        fallback_calls.append(share_token)
        return {"source": "static", "share_token": share_token}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="shares-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get("/api/v1/shared/public-token")

    assert result.status_code == 200
    assert result.json() == response
    assert calls == [
        ("authority", None, authority.db),
        ("shares", "public-token"),
    ]
    assert fallback_calls == []
    await host.close()
