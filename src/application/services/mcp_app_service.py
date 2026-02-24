"""MCP App Service.

Manages MCP App lifecycle: detection from tool discovery,
resource resolution, tool call proxying, and status management.
"""

import logging
from typing import Any, cast

from src.domain.model.mcp.app import (
    MCPApp,
    MCPAppResource,
    MCPAppSource,
    MCPAppStatus,
    MCPAppUIMetadata,
)
from src.domain.ports.mcp.app_repository_port import MCPAppRepositoryPort
from src.infrastructure.mcp.resource_resolver import MCPAppResourceResolver

logger = logging.getLogger(__name__)


class MCPAppService:
    """Service for managing MCP App lifecycle."""

    def __init__(
        self,
        app_repo: MCPAppRepositoryPort,
        resource_resolver: MCPAppResourceResolver,
    ) -> None:
        self._app_repo = app_repo
        self._resource_resolver = resource_resolver

    async def sync_apps_from_tools(
        self,
        project_id: str,
        server_id: str,
        server_name: str,
        tenant_id: str,
        tools: list[dict[str, Any]],
    ) -> list[MCPApp]:
        """Sync discovered tools to MCPApps.

        Wrapper around detect_apps_from_tools for use by MCPRuntimeService.
        """
        return await self.detect_apps_from_tools(
            server_id=server_id,
            project_id=project_id,
            tenant_id=tenant_id,
            server_name=server_name,
            tools=tools,
            source=MCPAppSource.TOOL_DISCOVERY,
        )

    async def detect_apps_from_tools(
        self,
        server_id: str,
        project_id: str,
        tenant_id: str,
        server_name: str,
        tools: list[dict[str, Any]],
        source: MCPAppSource = MCPAppSource.USER_ADDED,
    ) -> list[MCPApp]:
        """Scan discovered tools for _meta.ui.resourceUri and register as MCPApps.

        This is called after SandboxMCPServerManager.discover_tools() to
        auto-detect tools that declare interactive UIs.

        Args:
            server_id: The MCP server ID.
            project_id: Project ID for scoping.
            tenant_id: Tenant ID for multi-tenancy.
            server_name: Human-readable server name.
            tools: List of tool dicts from discovery (with _meta preserved).
            source: How the app was created.

        Returns:
            List of newly registered MCPApp entities.
        """
        apps = []

        for tool in tools:
            meta = tool.get("_meta")
            if not meta or not isinstance(meta, dict):
                continue

            ui_meta = meta.get("ui")
            if not ui_meta or not isinstance(ui_meta, dict):
                # SEP-1865: Check deprecated flat format _meta["ui/resourceUri"]
                deprecated_uri = meta.get("ui/resourceUri")
                if deprecated_uri:
                    ui_meta = {"resourceUri": deprecated_uri}
                else:
                    continue

            resource_uri = ui_meta.get("resourceUri", "")
            if not resource_uri:
                continue

            tool_name = tool.get("name", "")
            if not tool_name:
                continue

            # Check if already registered
            existing = await self._app_repo.find_by_server_and_tool(server_id, tool_name)
            if existing:
                # Compare ui_metadata to detect changes (e.g. resourceUri update)
                new_ui_metadata = MCPAppUIMetadata.from_dict(ui_meta)
                if existing.ui_metadata.to_dict() != new_ui_metadata.to_dict():
                    existing.ui_metadata = new_ui_metadata
                    existing.mark_discovered()
                    await self._app_repo.save(existing)
                    logger.info(
                        "Updated MCP App metadata: server=%s, tool=%s",
                        server_name,
                        tool_name,
                    )
                else:
                    logger.debug(
                        "MCP App already registered: server=%s, tool=%s",
                        server_name,
                        tool_name,
                    )
                apps.append(existing)
                continue

            # Register new app
            ui_metadata = MCPAppUIMetadata.from_dict(ui_meta)
            app = MCPApp(
                project_id=project_id,
                tenant_id=tenant_id,
                server_id=server_id,
                server_name=server_name,
                tool_name=tool_name,
                ui_metadata=ui_metadata,
                source=source,
                status=MCPAppStatus.DISCOVERED,
            )
            app = await self._app_repo.save(app)
            apps.append(app)

            logger.info(
                "Registered MCP App: id=%s, server=%s, tool=%s, uri=%s, source=%s",
                app.id,
                server_name,
                tool_name,
                resource_uri,
                source.value,
            )

        return apps

    async def resolve_resource(
        self,
        app_id: str,
        project_id: str,
    ) -> MCPApp:
        """Fetch and cache the HTML content for an MCP App.

        Args:
            app_id: The MCP App ID.
            project_id: Project ID for sandbox routing.

        Returns:
            Updated MCPApp with resolved resource.

        Raises:
            ValueError: If app not found or resource resolution fails.
        """
        app = await self._app_repo.find_by_id(app_id)
        if not app:
            raise ValueError(f"MCP App not found: {app_id}")

        app.mark_loading()
        await self._app_repo.save(app)

        try:
            resource = await self._resource_resolver.resolve(
                project_id=project_id,
                server_name=app.server_name,
                resource_uri=app.ui_metadata.resource_uri,
            )
            app.mark_ready(resource)
            await self._app_repo.save(app)

            logger.info(
                "Resolved MCP App resource: id=%s, size=%d bytes",
                app.id,
                resource.size_bytes,
            )
            return app

        except Exception as e:
            app.mark_error(str(e))
            await self._app_repo.save(app)
            raise

    async def get_app(self, app_id: str) -> MCPApp | None:
        """Get an MCP App by ID."""
        return await self._app_repo.find_by_id(app_id)

    async def get_app_by_server_and_tool(self, server_id: str, tool_name: str) -> MCPApp | None:
        """Get an MCP App by server and tool name."""
        return await self._app_repo.find_by_server_and_tool(server_id, tool_name)

    async def list_apps(
        self,
        project_id: str,
        include_disabled: bool = False,
    ) -> list[MCPApp]:
        """List all MCP Apps for a project."""
        return await self._app_repo.find_by_project(project_id, include_disabled)

    async def list_apps_by_tenant(
        self,
        tenant_id: str,
        include_disabled: bool = False,
    ) -> list[MCPApp]:
        """List all MCP Apps for a tenant (across all projects)."""
        return cast(list[MCPApp], await self._app_repo.find_by_tenant(tenant_id, include_disabled))

    async def list_ready_apps(self, project_id: str) -> list[MCPApp]:
        """List all ready-to-render MCP Apps for a project."""
        return await self._app_repo.find_ready_by_project(project_id)

    async def delete_app(self, app_id: str) -> bool:
        """Delete an MCP App."""
        return await self._app_repo.delete(app_id)

    async def delete_apps_by_server(self, server_id: str) -> int:
        """Delete all MCP Apps when a server is removed."""
        return await self._app_repo.delete_by_server(server_id)

    async def disable_apps_by_server(self, server_id: str) -> int:
        """Disable all MCP Apps when a server is disabled.

        Apps are marked DISABLED rather than deleted so they can be
        re-enabled when the server comes back online.
        """
        count = await self._app_repo.disable_by_server(server_id)
        if count > 0:
            logger.info("Disabled %d apps for server %s", count, server_id)
        return count

    async def disable_app(self, app_id: str) -> MCPApp | None:
        """Disable an MCP App."""
        app = await self._app_repo.find_by_id(app_id)
        if not app:
            return None
        app.mark_disabled()
        await self._app_repo.save(app)
        return app

    async def refresh_resource(
        self,
        app_id: str,
        project_id: str,
    ) -> MCPApp:
        """Re-fetch the HTML resource for an MCP App.

        Useful when the app has been rebuilt (e.g., by the agent).
        """
        return await self.resolve_resource(app_id, project_id)

    async def save_html_if_ready(
        self,
        app_id: str,
        resource_uri: str,
        html_content: str,
    ) -> MCPApp | None:
        """Persist agent-generated HTML to an MCPApp record, marking it READY.

        Called from the agent execution layer when the agent emits
        `mcp_app_result` with non-empty `resource_html`. Persisting the HTML
        ensures it survives page refreshes without requiring sandbox access.

        Args:
            app_id: The MCPApp ID.
            resource_uri: The ui:// URI of the resource.
            html_content: HTML content to persist.

        Returns:
            Updated MCPApp, or None if app not found.
        """
        app = await self._app_repo.find_by_id(app_id)
        if not app:
            logger.warning("MCPApp not found for html persistence: %s", app_id)
            return None

        resource = MCPAppResource(
            uri=resource_uri,
            html_content=html_content,
            size_bytes=len(html_content.encode("utf-8")),
        )
        app.mark_ready(resource)
        app = await self._app_repo.save(app)
        logger.info(
            "Persisted MCPApp html: id=%s, size=%d bytes",
            app_id,
            resource.size_bytes,
        )
        return app

    async def clear_resources_for_project(self, project_id: str) -> int:
        """Clear HTML resources for all MCPApps in a project.

        Called when a project sandbox is recreated so that MCPApps revert
        to DISCOVERED state. This prevents the frontend from showing stale
        READY apps whose resources no longer exist in the new sandbox.

        Args:
            project_id: The project ID.

        Returns:
            Number of apps whose resources were cleared.
        """
        apps = await self._app_repo.find_by_project(project_id, include_disabled=True)
        count = 0
        for app in apps:
            if app.status in (MCPAppStatus.READY, MCPAppStatus.LOADING, MCPAppStatus.ERROR):
                app.mark_discovered()
                await self._app_repo.save(app)
                count += 1
        if count > 0:
            logger.info("Cleared resources for %d MCPApps in project %s", count, project_id)
        return count
