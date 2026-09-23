"""Refresh scoped marketplace OAuth before managed MCP tools and App reads."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.application.services.marketplace_oauth import MarketplaceOAuth
from src.application.services.sandbox_mcp_server_manager import SandboxMCPServerManager
from src.infrastructure.adapters.secondary.persistence.models import MCPServer, Project
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.marketplace_credentials import open_transport, seal
from src.infrastructure.plugins.marketplace_oauth_protocol import OAuthError, oauth_config

_ACTIVATION: ContextVar[tuple[str, str, frozenset[str]] | None] = ContextVar(
    "marketplace_oauth_activation", default=None
)


@contextmanager
def marketplace_activation(
    tenant_id: str, project_id: str, server_ids: list[str]
) -> Iterator[None]:
    """Only the installing task may verify its just-configured, unpublished server generation."""
    token = _ACTIVATION.set((tenant_id, project_id, frozenset(server_ids)))
    try:
        yield
    finally:
        _ACTIVATION.reset(token)


class OAuthSandboxMCPServerManager(SandboxMCPServerManager):
    """The existing managed transport remains the only process and tool authority."""

    def __init__(self, *, db: AsyncSession, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.db = db
        self.runtime_service: Any = None
        self._refresh_lock = asyncio.Lock()

    async def require_sandbox(self, tenant_id: str, project_id: str, sandbox_id: str) -> None:
        if await self.tenant(project_id) != tenant_id:
            raise OAuthError("oauth_project_scope_mismatch")
        actual = await self._sandbox_resource.get_sandbox_id(project_id, tenant_id)
        if actual != sandbox_id:
            raise OAuthError("oauth_sandbox_scope_mismatch")

    async def tenant(self, project_id: str) -> str:
        tenant = await self.db.scalar(select(Project.tenant_id).where(Project.id == project_id))
        if tenant is None:
            raise OAuthError("oauth_project_unavailable")
        return tenant

    async def refresh(
        self,
        tenant_id: str | None,
        project_id: str,
        server_name: str | None,
        resource_uri: str | None = None,
    ) -> str:
        async with self._refresh_lock:
            actual_tenant = await self.tenant(project_id)
            if tenant_id is not None and tenant_id != actual_tenant:
                raise OAuthError("oauth_project_scope_mismatch")
            if server_name is None and resource_uri is not None:
                server_name = await self._resource_server(actual_tenant, project_id, resource_uri)
            await self._refresh(actual_tenant, project_id, server_name)
            return actual_tenant

    async def _resource_server(self, tenant_id: str, project_id: str, uri: str) -> str | None:
        rows = await self.db.scalars(
            select(MarketplaceRecordV3).where(
                MarketplaceRecordV3.kind == "installation",
                MarketplaceRecordV3.tenant_id == tenant_id,
                MarketplaceRecordV3.project_id == project_id,
            )
        )
        for row in rows:
            resources = row.payload.get("package", {}).get("resources", {})
            names = list(resources.get("mcp_servers", {}))
            for app in resources.get("apps", {}).values():
                if app.get("resource_uri") != uri or app.get("mcp_server") not in names:
                    continue
                index = names.index(app["mcp_server"])
                owned = row.payload.get("owned_servers", [])
                if index >= len(owned):
                    raise OAuthError("oauth_mcp_server_unavailable")
                server = await self.db.get(MCPServer, owned[index])
                if (
                    server is None
                    or server.tenant_id != tenant_id
                    or server.project_id != project_id
                ):
                    raise OAuthError("oauth_mcp_server_unavailable")
                return server.name
        return None

    async def _refresh(self, tenant_id: str, project_id: str, server_name: str | None) -> None:
        target = None
        if server_name is not None:
            target = await self.db.scalar(
                select(MCPServer).where(
                    MCPServer.tenant_id == tenant_id,
                    MCPServer.project_id == project_id,
                    MCPServer.name == server_name,
                )
            )
            if target is None or not target.enabled:
                raise OAuthError("oauth_mcp_server_unavailable")
            activation = _ACTIVATION.get()
            if (
                activation is not None
                and activation[:2] == (tenant_id, project_id)
                and target.id in activation[2]
            ):
                return
        installations = await self.db.scalars(
            select(MarketplaceRecordV3).where(
                MarketplaceRecordV3.kind == "installation",
                MarketplaceRecordV3.tenant_id == tenant_id,
                MarketplaceRecordV3.project_id == project_id,
            )
        )
        for installation in installations:
            payload = installation.payload
            if (
                target is not None
                and target.id in payload.get("owned_servers", [])
                and payload["status"] != "enabled"
            ):
                raise OAuthError("oauth_installation_not_enabled")
            if payload["status"] != "enabled":
                continue
            declared = payload["package"]["resources"].get("mcp_servers", {})
            for index, (name, config) in enumerate(declared.items()):
                owned = payload.get("owned_servers", [])
                if oauth_config(config) is None or index >= len(owned):
                    continue
                await self._refresh_server(
                    tenant_id, project_id, installation.id, name, config, owned[index], server_name
                )

    async def _refresh_server(
        self,
        tenant_id: str,
        project_id: str,
        installation_id: str,
        name: str,
        config: dict[str, Any],
        server_id: str,
        server_name: str | None,
    ) -> None:
        server = await self.db.get(MCPServer, server_id)
        if server is None or server.tenant_id != tenant_id or server.project_id != project_id:
            raise OAuthError("oauth_mcp_scope_mismatch")
        if server_name is not None and server.name != server_name:
            return
        if not server.enabled:
            if server_name is not None:
                raise OAuthError("oauth_mcp_server_unavailable")
            return
        # Never bind the rotation transaction to the caller's active connection.
        bind = self.db.bind
        engine = bind.engine if isinstance(bind, AsyncConnection) else bind
        async with async_sessionmaker(engine, expire_on_commit=False)() as grant_db:
            current = await grant_db.get(MCPServer, server.id)
            if (
                current is None
                or not current.enabled
                or current.tenant_id != tenant_id
                or current.project_id != project_id
            ):
                raise OAuthError("oauth_mcp_server_unavailable")
            oauth = MarketplaceOAuth(grant_db, tenant_id, project_id)
            try:
                bearer = await oauth.bearer(installation_id, name, config, require_enabled=True)
            except OAuthError as exc:
                if str(exc) == "oauth_invalid_grant":
                    await grant_db.commit()
                raise
            await grant_db.commit()
        if (
            open_transport(server.transport_config.get("headers", {}).get("Authorization"))
            == bearer
        ):
            return
        transport = {
            **server.transport_config,
            "headers": {
                **server.transport_config.get("headers", {}),
                "Authorization": seal(bearer),
            },
        }
        updated = await self.runtime_service.update_server(
            server_id=server.id, tenant_id=tenant_id, transport_config=transport
        )
        if updated.runtime_status == "error":
            raise OAuthError("oauth_mcp_reconfigure_failed")

    @override
    async def call_tool(
        self, project_id: str, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        from src.infrastructure.plugins.marketplace_snapshot_cache import (
            lease_marketplace_snapshots,
        )

        tenant_id = await self.refresh(None, project_id, server_name)
        async with lease_marketplace_snapshots(
            self.db, tenant_id, project_id, server_name=server_name, sandbox=self._sandbox_resource
        ):
            return await super().call_tool(project_id, server_name, tool_name, arguments)

    @override
    async def read_resource(
        self,
        project_id: str,
        uri: str,
        server_name: str | None = None,
        tenant_id: str | None = None,
    ) -> str | None:
        from src.infrastructure.plugins.marketplace_snapshot_cache import (
            lease_marketplace_snapshots,
        )

        tenant_id = await self.refresh(tenant_id, project_id, server_name, uri)
        async with lease_marketplace_snapshots(
            self.db, tenant_id, project_id, server_name=server_name, sandbox=self._sandbox_resource
        ):
            return await super().read_resource(project_id, uri, server_name, tenant_id)
