"""Unified MCP runtime service.

Orchestrates MCP Server + MCP App lifecycle as one runtime boundary, including:
- server create/update/delete/sync/test/reconcile
- app disable/delete/refresh during server lifecycle transitions
- runtime metadata persistence and lifecycle audit logging
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.mcp_app_service import MCPAppService
from src.domain.model.mcp.app import MCPApp
from src.domain.model.mcp.server import MCPServer
from src.domain.ports.services.sandbox_mcp_server_port import SandboxMCPServerStatus
from src.infrastructure.adapters.secondary.persistence.models import MCPLifecycleEvent, Project
from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
    SqlMCPAppRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
    SqlMCPServerRepository,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.application.services.sandbox_mcp_server_manager import SandboxMCPServerManager


def _utcnow() -> datetime:
    return datetime.now(UTC)


logger = logging.getLogger(__name__)


@dataclass
class MCPReconcileResult:
    """Reconcile result summary."""

    project_id: str
    total_enabled_servers: int
    already_running: int
    restored: int
    failed: int


class MCPRuntimeService:
    """Unified runtime lifecycle service for MCP servers and apps."""

    _ERROR_MESSAGES: dict[str, str] = {
        "create": "Failed to bootstrap MCP server runtime",
        "enable": "Failed to enable MCP server runtime",
        "reconfigure": "Failed to reconfigure MCP server runtime",
        "sync": "Failed to sync MCP server tools",
        "test_connection": "MCP server connection test failed",
        "reconcile": "Failed to reconcile MCP server runtime",
        "stop": "Failed to stop MCP server runtime",
    }

    def __init__(
        self,
        db: AsyncSession,
        server_repo: SqlMCPServerRepository,
        app_repo: SqlMCPAppRepository,
        app_service: MCPAppService,
        sandbox_manager: SandboxMCPServerManager,
        redis_client: Redis | None = None,
    ) -> None:
        self._db = db
        self._server_repo = server_repo
        self._app_repo = app_repo
        self._app_service = app_service
        self._sandbox_manager = sandbox_manager
        self._redis_client = redis_client

    async def create_server(
        self,
        *,
        tenant_id: str,
        project_id: str,
        name: str,
        description: str | None,
        server_type: str,
        transport_config: dict[str, Any],
        enabled: bool,
    ) -> MCPServer:
        """Create server and bootstrap runtime metadata/lifecycle."""
        project_result = await self._db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise PermissionError("Access denied")

        server_id = await self._server_repo.create(
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            description=description,
            server_type=server_type,
            transport_config=transport_config,
            enabled=enabled,
        )
        await self._record_event(
            tenant_id=tenant_id,
            project_id=project_id,
            server_id=server_id,
            event_type="server.create",
            status="success",
            metadata={
                "server_name": name,
                "server_type": server_type,
                "enabled": enabled,
            },
        )

        server = await self._server_repo.get_by_id(server_id)
        if not server:
            raise ValueError(f"MCP server not found: {server_id}")

        if not enabled:
            await self._server_repo.update_runtime_metadata(
                server_id=server_id,
                runtime_status="disabled",
                runtime_metadata={"last_disabled_at": _utcnow().isoformat()},
            )
            return (await self._server_repo.get_by_id(server_id)) or server

        try:
            await self._install_start_and_sync(server, tenant_id, reason="create")
        except Exception as exc:
            logger.exception("MCP runtime bootstrap failed during server create: server_id=%s", server.id)
            # Keep create behavior backward-compatible: create succeeds but marks runtime error.
            await self._server_repo.update_runtime_metadata(
                server_id=server.id,
                runtime_status="error",
                runtime_metadata=self._failure_runtime_metadata("create"),
            )
            await self._server_repo.update_discovered_tools(
                server_id=server.id,
                tools=[],
                last_sync_at=_utcnow(),
                sync_error=self._ERROR_MESSAGES["sync"],
            )
            await self._record_event(
                tenant_id=tenant_id,
                project_id=project_id,
                server_id=server.id,
                event_type="server.create_runtime_bootstrap",
                status="failed",
                error_message=str(exc),
            )

        return (await self._server_repo.get_by_id(server_id)) or server

    async def update_server(
        self,
        *,
        server_id: str,
        tenant_id: str,
        name: str | None = None,
        description: str | None = None,
        server_type: str | None = None,
        transport_config: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> MCPServer:
        """Update server config and reconcile lifecycle transitions."""
        server = await self.get_server_for_tenant(server_id, tenant_id)
        old_enabled = server.enabled
        old_name = server.name
        old_project_id = server.project_id

        await self._server_repo.update(
            server_id=server_id,
            name=name,
            description=description,
            server_type=server_type,
            transport_config=transport_config,
            enabled=enabled,
        )
        updated = await self.get_server_for_tenant(server_id, tenant_id)

        new_enabled = updated.enabled
        name_changed = name is not None and name != old_name
        config_changed = server_type is not None or transport_config is not None
        runtime_reconfigured = name_changed or config_changed

        if old_enabled != new_enabled:
            if new_enabled:
                try:
                    await self._install_start_and_sync(updated, tenant_id, reason="enable")
                except Exception:
                    logger.exception(
                        "MCP runtime bootstrap failed during server enable: server_id=%s", updated.id
                    )
                    await self._server_repo.update_runtime_metadata(
                        server_id=updated.id,
                        runtime_status="error",
                        runtime_metadata=self._failure_runtime_metadata("enable"),
                    )
            else:
                await self._stop_server_runtime(
                    updated,
                    reason="disable",
                    runtime_server_name=old_name,
                    runtime_project_id=old_project_id,
                )
        elif runtime_reconfigured and new_enabled:
            if old_project_id:
                old_stop_ok = await self._sandbox_manager.stop_server(old_project_id, old_name)
                if not old_stop_ok:
                    logger.warning(
                        "Failed to stop previous MCP runtime before reconfigure: "
                        "server_id=%s, old_name=%s",
                        updated.id,
                        old_name,
                    )
            try:
                await self._install_start_and_sync(updated, tenant_id, reason="reconfigure")
            except Exception:
                logger.exception(
                    "MCP runtime bootstrap failed during server reconfigure: server_id=%s",
                    updated.id,
                )
                await self._server_repo.update_runtime_metadata(
                    server_id=updated.id,
                    runtime_status="error",
                    runtime_metadata=self._failure_runtime_metadata("reconfigure"),
                )

        await self._record_event(
            tenant_id=tenant_id,
            project_id=updated.project_id or "",
            server_id=updated.id,
            event_type="server.update",
            status="success",
            metadata={
                "enabled": updated.enabled,
                "name_changed": name is not None,
                "transport_changed": config_changed,
            },
        )
        return await self.get_server_for_tenant(server_id, tenant_id)

    async def sync_server(self, server_id: str, tenant_id: str) -> MCPServer:
        """Sync server tools and app detection metadata."""
        server = await self.get_server_for_tenant(server_id, tenant_id)
        if not server.project_id:
            raise ValueError("MCP server has no associated project")
        if not server.enabled:
            raise ValueError(f"MCP server '{server.name}' is disabled")

        try:
            tools = await self._sandbox_manager.discover_tools(
                project_id=server.project_id,
                tenant_id=tenant_id,
                server_name=server.name,
                server_type=server.server_type,
                transport_config=server.transport_config or {},
            )
            await self._server_repo.update_discovered_tools(
                server_id=server.id,
                tools=tools,
                last_sync_at=_utcnow(),
                sync_error=None,
            )
            await self._server_repo.update_runtime_metadata(
                server_id=server.id,
                runtime_status="running",
                runtime_metadata={
                    "last_sync_at": _utcnow().isoformat(),
                    "last_sync_tools_count": len(tools),
                    "last_sync_status": "success",
                },
            )
            await self._record_event(
                tenant_id=tenant_id,
                project_id=server.project_id,
                server_id=server.id,
                event_type="server.sync",
                status="success",
                metadata={"tool_count": len(tools)},
            )

            # Sync apps from tools
            try:
                await self._app_service.sync_apps_from_tools(
                    project_id=server.project_id,
                    server_id=server.id,
                    server_name=server.name,
                    tenant_id=tenant_id,
                    tools=tools,
                )
            except Exception as e:
                logger.warning("Failed to sync MCP apps from tools for server %s: %s", server.id, e)
                # Don't fail the server sync if app sync fails, but log it.
                await self._record_event(
                    tenant_id=tenant_id,
                    project_id=server.project_id,
                    server_id=server.id,
                    event_type="app.sync_from_tools",
                    status="failed",
                    error_message=str(e),
                )
        except Exception as exc:
            logger.exception("MCP server sync failed: server_id=%s", server.id)
            await self._server_repo.update_discovered_tools(
                server_id=server.id,
                tools=server.discovered_tools or [],
                last_sync_at=_utcnow(),
                sync_error=self._ERROR_MESSAGES["sync"],
            )
            await self._server_repo.update_runtime_metadata(
                server_id=server.id,
                runtime_status="error",
                runtime_metadata={
                    "last_sync_at": _utcnow().isoformat(),
                    "last_sync_status": "failed",
                    **self._failure_runtime_metadata("sync"),
                },
            )
            await self._record_event(
                tenant_id=tenant_id,
                project_id=server.project_id,
                server_id=server.id,
                event_type="server.sync",
                status="failed",
                error_message=str(exc),
            )
            raise

        return await self.get_server_for_tenant(server_id, tenant_id)

    async def test_server(self, server_id: str, tenant_id: str) -> SandboxMCPServerStatus:
        """Test server runtime connectivity and persist metadata."""
        server = await self.get_server_for_tenant(server_id, tenant_id)
        if not server.project_id:
            raise ValueError("MCP server has no associated project")

        result = await self._sandbox_manager.test_connection(
            project_id=server.project_id,
            tenant_id=tenant_id,
            server_name=server.name,
            server_type=server.server_type,
            transport_config=server.transport_config or {},
        )
        test_status = "success" if result.status != "failed" else "failed"
        existing_runtime_metadata = server.runtime_metadata if server.runtime_metadata else {}
        test_error_metadata = (
            self._error_runtime_metadata("test_connection")
            if result.error
            else {
                "last_error": existing_runtime_metadata.get("last_error"),
                "last_error_code": existing_runtime_metadata.get("last_error_code"),
                "last_error_message": existing_runtime_metadata.get("last_error_message"),
            }
        )
        await self._server_repo.update_runtime_metadata(
            server_id=server.id,
            runtime_status=server.runtime_status if server.runtime_status else "unknown",
            runtime_metadata={
                "last_test_at": _utcnow().isoformat(),
                "last_test_status": test_status,
                "last_test_tool_count": result.tool_count,
                **test_error_metadata,
            },
        )
        await self._record_event(
            tenant_id=tenant_id,
            project_id=server.project_id,
            server_id=server.id,
            event_type="server.test_connection",
            status=test_status,
            error_message=result.error,
            metadata={"tool_count": result.tool_count},
        )
        return result

    async def delete_server(self, server_id: str, tenant_id: str) -> None:
        """Delete server and associated apps with lifecycle auditing."""
        server = await self.get_server_for_tenant(server_id, tenant_id)
        if server.enabled and server.project_id:
            await self._stop_server_runtime(server, reason="delete")

        deleted_apps = await self._app_service.delete_apps_by_server(server.id)
        await self._record_event(
            tenant_id=tenant_id,
            project_id=server.project_id or "",
            server_id=server.id,
            event_type="app.delete_by_server",
            status="success",
            metadata={"deleted_apps": deleted_apps},
        )

        await self._server_repo.delete(server.id)
        await self._record_event(
            tenant_id=tenant_id,
            project_id=server.project_id or "",
            server_id=None,
            event_type="server.delete",
            status="success",
            metadata={"deleted_server_id": server.id, "server_name": server.name},
        )

    async def refresh_app_resource(self, app_id: str, tenant_id: str) -> MCPApp:
        """Refresh app HTML resource and persist app lifecycle metadata."""
        app = await self._app_service.get_app(app_id)
        if not app:
            raise ValueError(f"MCP App not found: {app_id}")
        if app.tenant_id != tenant_id:
            raise PermissionError("Access denied")

        refreshed = await self._app_service.resolve_resource(app.id, app.project_id)
        await self._app_repo.update_lifecycle_metadata(
            refreshed.id,
            {
                "last_resource_refresh_at": _utcnow().isoformat(),
                "last_resource_refresh_status": "success",
                "resource_size_bytes": refreshed.resource.size_bytes if refreshed.resource else 0,
            },
        )
        await self._record_event(
            tenant_id=tenant_id,
            project_id=app.project_id,
            server_id=app.server_id,
            app_id=app.id,
            event_type="app.refresh_resource",
            status="success",
        )
        latest = await self._app_service.get_app(app_id)
        return latest or refreshed

    async def delete_app(self, app_id: str, tenant_id: str) -> bool:
        """Delete app with lifecycle audit."""
        app = await self._app_service.get_app(app_id)
        if not app:
            raise ValueError(f"MCP App not found: {app_id}")
        if app.tenant_id != tenant_id:
            raise PermissionError("Access denied")

        deleted = await self._app_service.delete_app(app_id)
        await self._record_event(
            tenant_id=tenant_id,
            project_id=app.project_id,
            server_id=app.server_id,
            app_id=None,
            event_type="app.delete",
            status="success" if deleted else "failed",
            metadata={"deleted_app_id": app.id, "tool_name": app.tool_name},
        )
        return deleted

    @asynccontextmanager
    async def _lock(self, key: str, timeout: int = 60):
        """Acquire a distributed lock."""
        if not self._redis_client:
            yield
            return

        lock = self._redis_client.lock(f"mcp:runtime:lock:{key}", timeout=timeout)
        acquired = await lock.acquire(blocking=False)
        if not acquired:
            logger.warning(f"Failed to acquire lock for {key}, skipping reconcile")
            # We yield None to signal skipping, but the caller needs to handle it.
            # Actually, let's just raise an exception or handle it gracefully.
            # If we can't lock, another process is reconciling. We can probably just return early.
            raise RuntimeError(f"Lock for {key} is busy")
        
        try:
            yield
        finally:
            with suppress(Exception):
                await lock.release()

    async def reconcile_project(self, project_id: str, tenant_id: str) -> MCPReconcileResult:
        """Reconcile enabled DB servers with sandbox runtime."""
        # Try to acquire lock to prevent concurrent reconciliation storms
        try:
            async with self._lock(f"reconcile:{project_id}"):
                return await self._reconcile_project_impl(project_id, tenant_id)
        except RuntimeError as e:
            if "Lock" in str(e):
                logger.info(f"Skipping reconcile for {project_id}: {e}")
                # Return a dummy result indicating skipped
                return MCPReconcileResult(
                    project_id=project_id,
                    total_enabled_servers=0,
                    already_running=0,
                    restored=0,
                    failed=0,
                )
            raise e

    async def _reconcile_project_impl(self, project_id: str, tenant_id: str) -> MCPReconcileResult:
        """Internal implementation of reconcile logic."""
        project_result = await self._db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if not project or project.tenant_id != tenant_id:
            raise PermissionError("Access denied")

        enabled_servers = await self._server_repo.list_by_project(project_id, enabled_only=True)
        for server in enabled_servers:
            if server.tenant_id != tenant_id:
                raise PermissionError("Access denied")

        sandbox_servers = await self._sandbox_manager.list_servers(project_id=project_id)
        running_names = {s.name for s in sandbox_servers if s.status == "running"}

        restored = 0
        failed = 0
        already_running = 0
        await self._record_event(
            tenant_id=tenant_id,
            project_id=project_id,
            event_type="project.reconcile",
            status="started",
            metadata={"enabled_servers": len(enabled_servers)},
        )

        for server in enabled_servers:
            if server.name in running_names:
                already_running += 1
                await self._server_repo.update_runtime_metadata(
                    server_id=server.id,
                    runtime_status="running",
                    runtime_metadata={
                        "last_reconcile_at": _utcnow().isoformat(),
                        "last_reconcile_status": "already_running",
                    },
                )
                continue
            try:
                await self._install_start_and_sync(server, tenant_id, reason="reconcile")
                restored += 1
                await self._server_repo.update_runtime_metadata(
                    server_id=server.id,
                    runtime_status="running",
                    runtime_metadata={
                        "last_reconcile_at": _utcnow().isoformat(),
                        "last_reconcile_status": "restored",
                    },
                )
            except Exception as exc:
                logger.exception("MCP server reconcile failed: server_id=%s", server.id)
                failed += 1
                await self._server_repo.update_runtime_metadata(
                    server_id=server.id,
                    runtime_status="error",
                    runtime_metadata={
                        "last_reconcile_at": _utcnow().isoformat(),
                        "last_reconcile_status": "failed",
                        **self._failure_runtime_metadata("reconcile"),
                    },
                )
                await self._record_event(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    server_id=server.id,
                    event_type="server.reconcile",
                    status="failed",
                    error_message=str(exc),
                )

        await self._record_event(
            tenant_id=tenant_id,
            project_id=project_id,
            event_type="project.reconcile",
            status="success",
            metadata={
                "enabled_servers": len(enabled_servers),
                "already_running": already_running,
                "restored": restored,
                "failed": failed,
            },
        )

        return MCPReconcileResult(
            project_id=project_id,
            total_enabled_servers=len(enabled_servers),
            already_running=already_running,
            restored=restored,
            failed=failed,
        )

    async def get_server_for_tenant(self, server_id: str, tenant_id: str) -> MCPServer:
        """Load server and enforce tenant ownership."""
        server = await self._server_repo.get_by_id(server_id)
        if not server:
            raise ValueError(f"MCP server not found: {server_id}")
        if server.tenant_id != tenant_id:
            raise PermissionError("Access denied")
        return server

    def _error_runtime_metadata(self, action: str) -> dict[str, str]:
        """Build a client-safe runtime error payload."""
        normalized_action = action.replace("-", "_")
        message = self._ERROR_MESSAGES.get(normalized_action, "MCP runtime operation failed")
        return {
            "last_error": message,
            "last_error_code": f"MCP_{normalized_action.upper()}_FAILED",
            "last_error_message": message,
        }

    def _failure_runtime_metadata(self, action: str) -> dict[str, Any]:
        """Build a runtime failure payload with action/timestamp metadata."""
        return {
            **self._error_runtime_metadata(action),
            "last_failed_action": action,
            "last_failed_at": _utcnow().isoformat(),
        }

    async def _install_start_and_sync(
        self,
        server: MCPServer,
        tenant_id: str,
        reason: str,
    ) -> None:
        """Install/start server, then sync tools/apps."""
        if not server.project_id:
            raise ValueError("MCP server has no associated project")

        await self._server_repo.update_runtime_metadata(
            server_id=server.id,
            runtime_status="starting",
            runtime_metadata={
                "last_start_attempt_at": _utcnow().isoformat(),
                "last_start_reason": reason,
            },
        )

        start_status = await self._sandbox_manager.install_and_start(
            project_id=server.project_id,
            tenant_id=tenant_id,
            server_name=server.name,
            server_type=server.server_type,
            transport_config=server.transport_config or {},
        )
        if start_status.status == "failed":
            raise RuntimeError(start_status.error or "install/start failed")

        await self._record_event(
            tenant_id=tenant_id,
            project_id=server.project_id,
            server_id=server.id,
            event_type="server.install_start",
            status="success",
            metadata={
                "server_status": start_status.status,
                "tool_count": start_status.tool_count,
                "pid": start_status.pid,
            },
        )

        tools = await self._sandbox_manager.discover_tools(
            project_id=server.project_id,
            tenant_id=tenant_id,
            server_name=server.name,
            server_type=server.server_type,
            transport_config=server.transport_config or {},
            ensure_running=False,
        )
        await self._server_repo.update_discovered_tools(
            server_id=server.id,
            tools=tools,
            last_sync_at=_utcnow(),
            sync_error=None,
        )
        await self._server_repo.update_runtime_metadata(
            server_id=server.id,
            runtime_status="running",
            runtime_metadata={
                "last_started_at": _utcnow().isoformat(),
                "last_sync_tools_count": len(tools),
                "last_sync_status": "success",
            },
        )
        await self._record_event(
            tenant_id=tenant_id,
            project_id=server.project_id,
            server_id=server.id,
            event_type="server.sync",
            status="success",
            metadata={"tool_count": len(tools)},
        )

        # Sync apps from tools
        try:
            await self._app_service.sync_apps_from_tools(
                project_id=server.project_id,
                server_id=server.id,
                server_name=server.name,
                tenant_id=tenant_id,
                tools=tools,
            )
        except Exception as e:
            logger.warning("Failed to sync MCP apps from tools for server %s: %s", server.id, e)
            # Don't fail the server sync if app sync fails, but log it.
            await self._record_event(
                tenant_id=tenant_id,
                project_id=server.project_id,
                server_id=server.id,
                event_type="app.sync_from_tools",
                status="failed",
                error_message=str(e),
            )

    async def _stop_server_runtime(
        self,
        server: MCPServer,
        reason: str,
        *,
        runtime_server_name: str | None = None,
        runtime_project_id: str | None = None,
    ) -> None:
        """Stop server and update runtime/app state."""
        runtime_server_name = runtime_server_name or server.name
        runtime_project_id = runtime_project_id or server.project_id
        stop_success = True
        if runtime_project_id:
            stop_success = await self._sandbox_manager.stop_server(
                runtime_project_id,
                runtime_server_name,
            )
        if not stop_success:
            await self._server_repo.update_runtime_metadata(
                server_id=server.id,
                runtime_status="error",
                runtime_metadata={
                    "last_stop_attempt_at": _utcnow().isoformat(),
                    "last_stop_reason": reason,
                    "last_stop_status": "failed",
                    "runtime_server_name": runtime_server_name,
                    **self._error_runtime_metadata("stop"),
                },
            )
            await self._record_event(
                tenant_id=server.tenant_id,
                project_id=server.project_id or "",
                server_id=server.id,
                event_type="server.stop",
                status="failed",
                error_message=self._ERROR_MESSAGES["stop"],
                metadata={"reason": reason, "runtime_server_name": runtime_server_name},
            )
            raise RuntimeError(f"Failed to stop MCP runtime '{runtime_server_name}'")

        disabled_apps = await self._app_service.disable_apps_by_server(server.id)
        await self._server_repo.update_runtime_metadata(
            server_id=server.id,
            runtime_status="disabled",
            runtime_metadata={
                "last_stopped_at": _utcnow().isoformat(),
                "last_stop_reason": reason,
                "last_stop_status": "success",
                "disabled_apps": disabled_apps,
                "runtime_server_name": runtime_server_name,
            },
        )
        await self._record_event(
            tenant_id=server.tenant_id,
            project_id=server.project_id or "",
            server_id=server.id,
            event_type="server.stop",
            status="success",
            metadata={
                "reason": reason,
                "disabled_apps": disabled_apps,
                "runtime_server_name": runtime_server_name,
            },
        )

    async def _record_event(
        self,
        *,
        tenant_id: str,
        project_id: str,
        event_type: str,
        status: str,
        server_id: str | None = None,
        app_id: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist lifecycle audit event."""
        if not tenant_id or not project_id:
            return

        event = MCPLifecycleEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            server_id=server_id,
            app_id=app_id,
            event_type=event_type,
            status=status,
            error_message=error_message,
            metadata_json=metadata or {},
        )
        self._db.add(event)
        await self._db.flush()
