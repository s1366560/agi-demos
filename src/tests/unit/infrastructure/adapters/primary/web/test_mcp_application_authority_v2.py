"""Request-lifetime coverage for the MCP application V2 authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.mcp_application_authority_v2 import (
    MCPApplicationAuthorityV2,
    mcp_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import mcp as mcp_router
from src.infrastructure.adapters.primary.web.routers.mcp import apps, servers, tools
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]
_MCP_ENDPOINTS = (
    apps.list_mcp_apps,
    apps.proxy_tool_call_direct,
    apps.get_mcp_app,
    apps.get_mcp_app_resource,
    apps.proxy_tool_call,
    apps.delete_mcp_app,
    apps.refresh_mcp_app_resource,
    apps.proxy_resource_read,
    apps.proxy_resource_list,
    servers.create_mcp_server,
    servers.list_mcp_servers,
    servers.get_mcp_server,
    servers.update_mcp_server,
    servers.delete_mcp_server,
    servers.sync_mcp_server_tools,
    servers.test_mcp_server_connection,
    servers.reconcile_mcp_project,
    servers.get_mcp_health_summary,
    servers.get_mcp_server_health,
    servers.list_mcp_server_prompts,
    servers.set_mcp_server_log_level,
    servers.list_mcp_server_logs,
    tools.list_all_mcp_tools,
    tools.call_mcp_tool,
    mcp_router.create_mcp_server_root,
    mcp_router.list_mcp_servers_root,
)


class _TrackedSandboxAdapter(MCPSandboxAdapter):
    def __init__(self) -> None:
        self.close_calls = 0

    async def sync_from_docker(self) -> int:
        return 0

    async def close(self) -> None:
        self.close_calls += 1


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "POST",
            "path": "/api/v1/mcp/apps",
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize("endpoint", _MCP_ENDPOINTS)
def test_mcp_routes_require_one_generation_owned_authority(endpoint: Any) -> None:
    parameter = signature(endpoint).parameters["authority"]

    assert parameter.default.dependency is mcp_application_authority_dependency_v2


async def test_authority_uses_tenant_scope_pinned_generation_and_request_db() -> None:
    adapter = _TrackedSandboxAdapter()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=lambda: adapter)
    )
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=93,
        version=93,
    )
    assert publication.accepted is True
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = mcp_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                tenant_id="tenant-a",
                db=db,
            )
            authority = await anext(dependency)

            assert isinstance(authority, MCPApplicationAuthorityV2)
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 93
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.db is db
            assert authority.tenant_id == "tenant-a"
            assert authority.user_id == "user-a"
            assert authority.services.app_service._app_repo._session is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-mcp-authority",
                "method": "POST",
                "path": "/api/v1/mcp/apps",
            }
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()

    assert adapter.close_calls == 1


async def test_authority_propagates_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.mcp_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = mcp_application_authority_dependency_v2(
        request=_request(),
        current_user=user,
        tenant_id="tenant-a",
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"
