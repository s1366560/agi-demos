"""Unit tests for MCPRuntimeService."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.mcp_runtime_service import MCPRuntimeService
from src.domain.model.mcp.server import MCPServer, MCPServerConfig
from src.domain.model.mcp.transport import TransportType
from src.domain.ports.services.sandbox_mcp_server_port import SandboxMCPServerStatus


def _make_server(
    server_id: str = "srv-1",
    enabled: bool = True,
    *,
    name: str = "demo-server",
    project_id: str = "proj-1",
    transport_config: dict | None = None,
) -> MCPServer:
    tc = transport_config or {"command": "node", "args": ["server.js"]}
    cmd = [tc.get("command", "node"), *tc.get("args", [])]
    config = MCPServerConfig(
        server_name=name,
        tenant_id="tenant-1",
        transport_type=TransportType.LOCAL,
        enabled=enabled,
        command=cmd,
    )
    return MCPServer(
        id=server_id,
        tenant_id="tenant-1",
        project_id=project_id,
        name=name,
        config=config,
        enabled=enabled,
    )


@pytest.mark.unit
class TestMCPRuntimeService:
    async def test_create_server_enabled_bootstraps_runtime(self):
        project_repo = SimpleNamespace(
            find_by_id=AsyncMock(return_value=SimpleNamespace(id="proj-1", tenant_id="tenant-1"))
        )
        server_repo = SimpleNamespace(
            create=AsyncMock(return_value="srv-1"),
            get_by_id=AsyncMock(side_effect=[_make_server(), _make_server()]),
            update_runtime_metadata=AsyncMock(return_value=True),
            update_discovered_tools=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace(
            disable_apps_by_server=AsyncMock(return_value=0),
            delete_apps_by_server=AsyncMock(return_value=0),
            get_app=AsyncMock(return_value=None),
            resolve_resource=AsyncMock(return_value=None),
            delete_app=AsyncMock(return_value=True),
        )
        sandbox_manager = SimpleNamespace(
            install_and_start=AsyncMock(
                return_value=SandboxMCPServerStatus(
                    name="demo-server",
                    server_type="stdio",
                    status="running",
                    tool_count=1,
                    pid=1234,
                )
            ),
            discover_tools=AsyncMock(return_value=[{"name": "hello_tool"}]),
            stop_server=AsyncMock(return_value=True),
            test_connection=AsyncMock(),
            list_servers=AsyncMock(return_value=[]),
        )

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=project_repo,  # type: ignore[arg-type]
        )

        server = await service.create_server(
            tenant_id="tenant-1",
            project_id="proj-1",
            name="demo-server",
            description="demo",
            server_type="stdio",
            transport_config={"command": "node", "args": ["server.js"]},
            enabled=True,
        )

        assert server.id == "srv-1"
        assert server_repo.update_discovered_tools.await_count == 1
        assert server_repo.update_runtime_metadata.await_count >= 1

    async def test_create_server_rejects_cross_tenant_project(self):
        project_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=None))
        server_repo = SimpleNamespace(
            create=AsyncMock(return_value="srv-1"),
            get_by_id=AsyncMock(return_value=_make_server()),
            update_runtime_metadata=AsyncMock(return_value=True),
            update_discovered_tools=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace(
            disable_apps_by_server=AsyncMock(return_value=0),
            delete_apps_by_server=AsyncMock(return_value=0),
            get_app=AsyncMock(return_value=None),
            resolve_resource=AsyncMock(return_value=None),
            delete_app=AsyncMock(return_value=True),
        )
        sandbox_manager = SimpleNamespace(
            install_and_start=AsyncMock(),
            discover_tools=AsyncMock(return_value=[]),
            stop_server=AsyncMock(return_value=True),
            test_connection=AsyncMock(),
            list_servers=AsyncMock(return_value=[]),
        )

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=project_repo,  # type: ignore[arg-type]
        )

        with pytest.raises(PermissionError, match="Access denied"):
            await service.create_server(
                tenant_id="tenant-1",
                project_id="proj-other",
                name="demo-server",
                description="demo",
                server_type="stdio",
                transport_config={"command": "node", "args": ["server.js"]},
                enabled=True,
            )

        server_repo.create.assert_not_called()

    async def test_update_server_disable_with_rename_stops_old_runtime_name(self):
        old_server = _make_server(name="old-server", enabled=True)
        updated_server = _make_server(name="new-server", enabled=False)
        server_repo = SimpleNamespace(
            get_by_id=AsyncMock(side_effect=[old_server, updated_server, updated_server]),
            update=AsyncMock(return_value=True),
            update_runtime_metadata=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace(
            disable_apps_by_server=AsyncMock(return_value=1),
            delete_apps_by_server=AsyncMock(return_value=0),
            get_app=AsyncMock(return_value=None),
            resolve_resource=AsyncMock(return_value=None),
            delete_app=AsyncMock(return_value=True),
        )
        sandbox_manager = SimpleNamespace(
            stop_server=AsyncMock(return_value=True),
            install_and_start=AsyncMock(),
            discover_tools=AsyncMock(),
            test_connection=AsyncMock(),
            list_servers=AsyncMock(return_value=[]),
        )

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=SimpleNamespace(),  # type: ignore[arg-type]
        )

        await service.update_server(
            server_id="srv-1",
            tenant_id="tenant-1",
            name="new-server",
            enabled=False,
        )

        sandbox_manager.stop_server.assert_awaited_once_with("proj-1", "old-server")

    async def test_update_server_reconfigure_with_rename_stops_old_runtime_before_restart(self):
        old_server = _make_server(name="old-server", enabled=True)
        updated_server = _make_server(
            name="new-server",
            enabled=True,
            transport_config={"command": "node", "args": ["new-server.js"]},
        )
        server_repo = SimpleNamespace(
            get_by_id=AsyncMock(side_effect=[old_server, updated_server, updated_server]),
            update=AsyncMock(return_value=True),
            update_runtime_metadata=AsyncMock(return_value=True),
            update_discovered_tools=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace(
            disable_apps_by_server=AsyncMock(return_value=0),
            delete_apps_by_server=AsyncMock(return_value=0),
            get_app=AsyncMock(return_value=None),
            resolve_resource=AsyncMock(return_value=None),
            delete_app=AsyncMock(return_value=True),
        )
        sandbox_manager = SimpleNamespace(
            stop_server=AsyncMock(return_value=True),
            install_and_start=AsyncMock(
                return_value=SandboxMCPServerStatus(
                    name="new-server",
                    server_type="stdio",
                    status="running",
                    tool_count=1,
                )
            ),
            discover_tools=AsyncMock(return_value=[{"name": "hello_tool"}]),
            test_connection=AsyncMock(),
            list_servers=AsyncMock(return_value=[]),
        )

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=SimpleNamespace(),  # type: ignore[arg-type]
        )

        await service.update_server(
            server_id="srv-1",
            tenant_id="tenant-1",
            name="new-server",
            transport_config={"command": "node", "args": ["new-server.js"]},
        )

        sandbox_manager.stop_server.assert_awaited_once_with("proj-1", "old-server")
        sandbox_manager.install_and_start.assert_awaited_once()

    async def test_delete_server_stops_runtime_and_deletes_apps(self):
        server = _make_server(enabled=True)
        server_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=server),
            update_runtime_metadata=AsyncMock(return_value=True),
            delete=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace(
            disable_apps_by_server=AsyncMock(return_value=2),
            delete_apps_by_server=AsyncMock(return_value=2),
            get_app=AsyncMock(return_value=None),
            resolve_resource=AsyncMock(return_value=None),
            delete_app=AsyncMock(return_value=True),
        )
        sandbox_manager = SimpleNamespace(
            stop_server=AsyncMock(return_value=True),
        )

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=SimpleNamespace(),  # type: ignore[arg-type]
        )

        await service.delete_server("srv-1", "tenant-1")

        sandbox_manager.stop_server.assert_awaited_once()
        app_service.delete_apps_by_server.assert_awaited_once_with("srv-1")
        server_repo.delete.assert_awaited_once_with("srv-1")

    async def test_delete_server_proceeds_when_runtime_stop_fails(self):
        """Delete should proceed with cleanup even when runtime stop fails."""
        server = _make_server(enabled=True)
        server_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=server),
            update_runtime_metadata=AsyncMock(return_value=True),
            delete=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace(
            disable_apps_by_server=AsyncMock(return_value=0),
            delete_apps_by_server=AsyncMock(return_value=0),
            get_app=AsyncMock(return_value=None),
            resolve_resource=AsyncMock(return_value=None),
            delete_app=AsyncMock(return_value=True),
        )
        sandbox_manager = SimpleNamespace(
            stop_server=AsyncMock(return_value=False),
        )

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=SimpleNamespace(),  # type: ignore[arg-type]
        )

        # Should NOT raise -- delete proceeds despite stop failure
        await service.delete_server("srv-1", "tenant-1")

        # Apps and server record should still be cleaned up
        app_service.delete_apps_by_server.assert_awaited_once_with("srv-1")
        server_repo.delete.assert_awaited_once_with("srv-1")

    async def test_reconcile_project_restores_missing_runtime_servers(self):
        project_repo = SimpleNamespace(
            find_by_id=AsyncMock(return_value=SimpleNamespace(id="proj-1", tenant_id="tenant-1"))
        )
        server = _make_server(enabled=True)
        server_repo = SimpleNamespace(
            list_by_project=AsyncMock(return_value=[server]),
            update_runtime_metadata=AsyncMock(return_value=True),
            update_discovered_tools=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace(
            disable_apps_by_server=AsyncMock(return_value=0),
            delete_apps_by_server=AsyncMock(return_value=0),
            get_app=AsyncMock(return_value=None),
            resolve_resource=AsyncMock(return_value=None),
            delete_app=AsyncMock(return_value=True),
        )
        sandbox_manager = SimpleNamespace(
            list_servers=AsyncMock(return_value=[]),
            install_and_start=AsyncMock(
                return_value=SandboxMCPServerStatus(
                    name="demo-server",
                    server_type="stdio",
                    status="running",
                )
            ),
            discover_tools=AsyncMock(return_value=[]),
        )

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=project_repo,  # type: ignore[arg-type]
        )

        result = await service.reconcile_project("proj-1", "tenant-1")

        assert result is not None
        assert result.restored == 1
        assert result.failed == 0
        sandbox_manager.install_and_start.assert_awaited_once()

    async def test_reconcile_project_acquires_lock(self):
        project_repo = SimpleNamespace(
            find_by_id=AsyncMock(return_value=SimpleNamespace(id="proj-1", tenant_id="tenant-1"))
        )
        server_repo = SimpleNamespace(
            list_by_project=AsyncMock(return_value=[]),
            update_runtime_metadata=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace()
        sandbox_manager = SimpleNamespace(
            list_servers=AsyncMock(return_value=[]),
        )

        # Mock Redis lock
        lock_mock = AsyncMock()
        lock_mock.acquire = AsyncMock(return_value=True)
        lock_mock.release = AsyncMock()

        redis_client = SimpleNamespace(lock=lambda key, timeout: lock_mock)

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=project_repo,  # type: ignore[arg-type]
            redis_client=redis_client,
        )

        await service.reconcile_project("proj-1", "tenant-1")

        # Verify lock was acquired and released
        assert lock_mock.acquire.await_count == 1
        assert lock_mock.release.await_count == 1

    async def test_reconcile_project_skips_when_lock_busy(self):
        server_repo = SimpleNamespace()
        app_repo = SimpleNamespace()
        app_service = SimpleNamespace()
        sandbox_manager = SimpleNamespace()

        # Mock Redis lock failing to acquire
        lock_mock = AsyncMock()
        lock_mock.acquire = AsyncMock(return_value=False)
        lock_mock.release = AsyncMock()

        redis_client = SimpleNamespace(lock=lambda key, timeout: lock_mock)

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=SimpleNamespace(),  # type: ignore[arg-type]
            redis_client=redis_client,
        )

        result = await service.reconcile_project("proj-1", "tenant-1")

        # Verify skipped result returns None (MCPLockBusyError caught)
        assert result is None

        # Lock acquire was attempted
        assert lock_mock.acquire.await_count == 1
        # Release is NOT called because _lock raises MCPLockBusyError before yield
        assert lock_mock.release.await_count == 0

    async def test_reconcile_project_rejects_cross_tenant_project(self):
        project_repo = SimpleNamespace(
            find_by_id=AsyncMock(
                return_value=SimpleNamespace(id="proj-other", tenant_id="tenant-other")
            )
        )
        server_repo = SimpleNamespace(
            list_by_project=AsyncMock(return_value=[]),
            update_runtime_metadata=AsyncMock(return_value=True),
            update_discovered_tools=AsyncMock(return_value=True),
        )
        app_repo = SimpleNamespace(update_lifecycle_metadata=AsyncMock(return_value=True))
        app_service = SimpleNamespace(
            disable_apps_by_server=AsyncMock(return_value=0),
            delete_apps_by_server=AsyncMock(return_value=0),
            get_app=AsyncMock(return_value=None),
            resolve_resource=AsyncMock(return_value=None),
            delete_app=AsyncMock(return_value=True),
        )
        sandbox_manager = SimpleNamespace(
            list_servers=AsyncMock(return_value=[]),
            install_and_start=AsyncMock(),
            discover_tools=AsyncMock(),
        )

        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=app_repo,  # type: ignore[arg-type]
            app_service=app_service,  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=project_repo,  # type: ignore[arg-type]
        )

        with pytest.raises(PermissionError, match="Access denied"):
            await service.reconcile_project("proj-other", "tenant-1")

    async def test_list_server_prompts_delegates_to_sandbox_manager(self):
        server = _make_server()
        server_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=server))
        sandbox_manager = SimpleNamespace(
            list_prompts=AsyncMock(return_value=[{"name": "review"}]),
        )
        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=SimpleNamespace(),  # type: ignore[arg-type]
            app_service=SimpleNamespace(),  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=AsyncMock(),
            project_repo=SimpleNamespace(),  # type: ignore[arg-type]
        )

        prompts = await service.list_server_prompts("srv-1", "tenant-1")

        assert prompts == [{"name": "review"}]
        sandbox_manager.list_prompts.assert_awaited_once_with(
            project_id="proj-1",
            server_name="demo-server",
        )

    async def test_set_server_log_level_delegates_and_records_event(self):
        server = _make_server()
        server_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=server))
        sandbox_manager = SimpleNamespace(set_log_level=AsyncMock(return_value=True))
        lifecycle_event_repo = AsyncMock()
        service = MCPRuntimeService(
            server_repo=server_repo,  # type: ignore[arg-type]
            app_repo=SimpleNamespace(),  # type: ignore[arg-type]
            app_service=SimpleNamespace(),  # type: ignore[arg-type]
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=lifecycle_event_repo,
            project_repo=SimpleNamespace(),  # type: ignore[arg-type]
        )

        success = await service.set_server_log_level("srv-1", "tenant-1", "debug")

        assert success is True
        sandbox_manager.set_log_level.assert_awaited_once_with(
            project_id="proj-1",
            server_name="demo-server",
            level="debug",
        )
        lifecycle_event_repo.record_event.assert_awaited_once()
