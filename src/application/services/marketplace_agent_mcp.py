"""Agent MCP dispatch through the operation-scoped managed runtime authority."""

from __future__ import annotations

import asyncio
from typing import Any

from src.application.services.marketplace_oauth_runtime import OAuthSandboxMCPServerManager
from src.infrastructure.plugins.marketplace_oauth_protocol import OAuthError
from src.infrastructure.plugins.v2.boundary import current_operation_context_v2
from src.infrastructure.plugins.v2.mcp_services import (
    MCP_APPLICATION_SERVICE_V2,
    MCPApplicationResolverProtocolV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

_DISCOVERY_LOCK = "service:operation.marketplace-mcp-discovery-lock"


async def agent_mcp_discover(sandbox_id: str, server_name: str) -> list[dict[str, Any]]:
    """Refresh before discovery, retaining the invocation's scope and snapshot lease."""
    from src.infrastructure.plugins.marketplace_snapshot_cache import lease_marketplace_snapshots

    operation = current_operation_context_v2()
    try:
        lock = operation.require(_DISCOVERY_LOCK)
    except RuntimeV2Error as exc:
        if exc.code != "missing_service":
            raise
        lock = asyncio.Lock()
        _ = operation.provide(_DISCOVERY_LOCK, lock)
    if not isinstance(lock, asyncio.Lock):
        raise OAuthError("oauth_runtime_unavailable")
    # Discovery tasks share the operation's AsyncSession, which cannot execute
    # concurrent transactions. The lock belongs to this operation only.
    async with lock:
        manager, tenant_id, project_id = await agent_mcp_manager(sandbox_id)
        _ = await manager.refresh(tenant_id, project_id, server_name)
        async with lease_marketplace_snapshots(
            manager.db,
            tenant_id,
            project_id,
            server_name=server_name,
            sandbox=manager._sandbox_resource,  # pyright: ignore[reportPrivateUsage]
        ):
            return await manager.discover_tools(
                project_id=project_id,
                tenant_id=tenant_id,
                server_name=server_name,
                server_type="",
                transport_config={},
                ensure_running=False,
            )


async def agent_mcp_manager(sandbox_id: str) -> tuple[OAuthSandboxMCPServerManager, str, str]:
    operation = current_operation_context_v2()
    scope = operation.context.scope
    if not scope.tenant_id or not scope.project_id:
        raise OAuthError("oauth_project_scope_required")
    resolver = operation.require(MCP_APPLICATION_SERVICE_V2)
    if not isinstance(resolver, MCPApplicationResolverProtocolV2):
        raise OAuthError("oauth_runtime_unavailable")
    manager = resolver.resolve(operation).sandbox_manager
    if not isinstance(manager, OAuthSandboxMCPServerManager):
        raise OAuthError("oauth_runtime_unavailable")
    await manager.require_sandbox(scope.tenant_id, scope.project_id, sandbox_id)
    return manager, scope.tenant_id, scope.project_id


async def agent_mcp_call(
    sandbox_id: str, server_name: str, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    manager, _tenant_id, project_id = await agent_mcp_manager(sandbox_id)
    result = await manager.call_tool(project_id, server_name, tool_name, arguments)
    return {"content": result.content, "isError": result.is_error}


async def agent_mcp_resource(sandbox_id: str, server_name: str, uri: str) -> str:
    manager, tenant_id, project_id = await agent_mcp_manager(sandbox_id)
    return await manager.read_resource(project_id, uri, server_name, tenant_id) or ""
