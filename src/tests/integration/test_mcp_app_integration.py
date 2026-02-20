"""Integration tests for MCP App repository and service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.mcp_app_service import MCPAppService
from src.domain.model.mcp.app import (
    MCPApp,
    MCPAppResource,
    MCPAppSource,
    MCPAppStatus,
    MCPAppUIMetadata,
)
from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
    SqlMCPAppRepository,
)


@pytest.mark.integration
class TestSqlMCPAppRepository:
    """Integration tests for SqlMCPAppRepository with in-memory SQLite."""

    async def test_save_and_find_by_id(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        app = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="test-server",
            tool_name="generate_report",
            ui_metadata=MCPAppUIMetadata(
                resource_uri="ui://test-server/report.html",
                title="Sales Report",
            ),
            source=MCPAppSource.USER_ADDED,
        )

        saved = await repo.save(app)
        assert saved.id == app.id

        found = await repo.find_by_id(app.id)
        assert found is not None
        assert found.id == app.id
        assert found.project_id == "proj-1"
        assert found.tenant_id == "tenant-1"
        assert found.server_name == "test-server"
        assert found.tool_name == "generate_report"
        assert found.ui_metadata.resource_uri == "ui://test-server/report.html"
        assert found.ui_metadata.title == "Sales Report"
        assert found.source == MCPAppSource.USER_ADDED
        assert found.status == MCPAppStatus.DISCOVERED

    async def test_find_by_id_not_found(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        found = await repo.find_by_id("nonexistent-id")
        assert found is None

    async def test_find_by_server_and_tool(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        app = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="my-server",
            tool_name="my_tool",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://my-server/app.html"),
        )
        await repo.save(app)

        found = await repo.find_by_server_and_tool("srv-1", "my_tool")
        assert found is not None
        assert found.id == app.id

        not_found = await repo.find_by_server_and_tool("srv-1", "other_tool")
        assert not_found is None

    async def test_find_by_project(self, db_session):
        repo = SqlMCPAppRepository(db_session)

        # Create apps in two different projects
        for i in range(3):
            app = MCPApp(
                project_id="proj-A",
                tenant_id="tenant-1",
                server_id=f"srv-{i}",
                server_name=f"server-{i}",
                tool_name=f"tool_{i}",
                ui_metadata=MCPAppUIMetadata(resource_uri=f"ui://s{i}/app.html"),
            )
            await repo.save(app)

        other_app = MCPApp(
            project_id="proj-B",
            tenant_id="tenant-1",
            server_id="srv-other",
            server_name="other-server",
            tool_name="other_tool",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://other/app.html"),
        )
        await repo.save(other_app)

        results = await repo.find_by_project("proj-A")
        assert len(results) == 3

        results_b = await repo.find_by_project("proj-B")
        assert len(results_b) == 1

    async def test_find_by_project_excludes_disabled(self, db_session):
        repo = SqlMCPAppRepository(db_session)

        app1 = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="server-1",
            tool_name="tool_1",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://s1/a.html"),
        )
        await repo.save(app1)

        app2 = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-2",
            server_name="server-2",
            tool_name="tool_2",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://s2/a.html"),
            status=MCPAppStatus.DISABLED,
        )
        await repo.save(app2)

        # Without include_disabled
        results = await repo.find_by_project("proj-1", include_disabled=False)
        assert len(results) == 1
        assert results[0].id == app1.id

        # With include_disabled
        results_all = await repo.find_by_project("proj-1", include_disabled=True)
        assert len(results_all) == 2

    async def test_update_status(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        app = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="server",
            tool_name="tool",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://s/a.html"),
        )
        await repo.save(app)

        # Update lifecycle
        app.mark_loading()
        await repo.save(app)
        found = await repo.find_by_id(app.id)
        assert found.status == MCPAppStatus.LOADING
        assert found.lifecycle_metadata.get("last_status") == MCPAppStatus.LOADING.value

        app.mark_error("timeout")
        await repo.save(app)
        found = await repo.find_by_id(app.id)
        assert found.status == MCPAppStatus.ERROR
        assert found.error_message == "timeout"
        assert found.lifecycle_metadata.get("last_error") == "timeout"

    async def test_delete(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        app = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="server",
            tool_name="tool",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://s/a.html"),
        )
        await repo.save(app)

        deleted = await repo.delete(app.id)
        assert deleted is True

        found = await repo.find_by_id(app.id)
        assert found is None

        deleted_again = await repo.delete(app.id)
        assert deleted_again is False

    async def test_delete_by_server(self, db_session):
        repo = SqlMCPAppRepository(db_session)

        for i in range(3):
            app = MCPApp(
                project_id="proj-1",
                tenant_id="tenant-1",
                server_id="srv-target",
                server_name="target-server",
                tool_name=f"tool_{i}",
                ui_metadata=MCPAppUIMetadata(resource_uri=f"ui://t/a{i}.html"),
            )
            await repo.save(app)

        other = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-keep",
            server_name="keep-server",
            tool_name="tool_keep",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://k/a.html"),
        )
        await repo.save(other)

        count = await repo.delete_by_server("srv-target")
        assert count == 3

        # The other server's app should still exist
        found = await repo.find_by_id(other.id)
        assert found is not None


@pytest.mark.integration
class TestMCPAppServiceIntegration:
    """Integration tests for MCPAppService with real repository."""

    async def test_detect_and_list(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        resolver = MagicMock()
        service = MCPAppService(app_repo=repo, resource_resolver=resolver)

        tools = [
            {
                "name": "chart_tool",
                "description": "Generates charts",
                "_meta": {
                    "ui": {
                        "resourceUri": "ui://chart-server/chart.html",
                        "title": "Chart Viewer",
                    }
                },
            },
            {
                "name": "plain_tool",
                "description": "No UI",
            },
        ]

        apps = await service.detect_apps_from_tools(
            server_id="srv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="chart-server",
            tools=tools,
        )
        assert len(apps) == 1
        assert apps[0].tool_name == "chart_tool"

        # List should return the registered app
        listed = await service.list_apps("proj-1")
        assert len(listed) == 1
        assert listed[0].id == apps[0].id

    async def test_detect_idempotent(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        resolver = MagicMock()
        service = MCPAppService(app_repo=repo, resource_resolver=resolver)

        tools = [
            {
                "name": "tool_a",
                "_meta": {"ui": {"resourceUri": "ui://s/a.html"}},
            },
        ]

        apps1 = await service.detect_apps_from_tools(
            server_id="srv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="server",
            tools=tools,
        )
        apps2 = await service.detect_apps_from_tools(
            server_id="srv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="server",
            tools=tools,
        )

        # Should return same app, not create duplicate
        assert len(apps1) == 1
        assert len(apps2) == 1
        assert apps1[0].id == apps2[0].id

        listed = await service.list_apps("proj-1")
        assert len(listed) == 1

    async def test_resolve_resource(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(
            return_value=MCPAppResource(
                uri="ui://s/a.html",
                html_content="<h1>Hello</h1>",
                size_bytes=14,
            )
        )
        service = MCPAppService(app_repo=repo, resource_resolver=mock_resolver)

        # Register an app first
        app = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="server",
            tool_name="tool",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://s/a.html"),
        )
        await repo.save(app)

        # Resolve resource
        resolved = await service.resolve_resource(app.id, "proj-1")
        assert resolved.status == MCPAppStatus.READY
        assert resolved.resource is not None
        assert resolved.resource.html_content == "<h1>Hello</h1>"

        mock_resolver.resolve.assert_called_once_with(
            project_id="proj-1",
            server_name="server",
            resource_uri="ui://s/a.html",
        )

    async def test_resolve_resource_error(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(side_effect=ValueError("Connection failed"))
        service = MCPAppService(app_repo=repo, resource_resolver=mock_resolver)

        app = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="server",
            tool_name="tool",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://s/a.html"),
        )
        await repo.save(app)

        with pytest.raises(ValueError, match="Connection failed"):
            await service.resolve_resource(app.id, "proj-1")

        # App should be in error state
        found = await repo.find_by_id(app.id)
        assert found.status == MCPAppStatus.ERROR
        assert "Connection failed" in found.error_message

    async def test_disable_app(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        resolver = MagicMock()
        service = MCPAppService(app_repo=repo, resource_resolver=resolver)

        app = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="server",
            tool_name="tool",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://s/a.html"),
        )
        await repo.save(app)

        disabled = await service.disable_app(app.id)
        assert disabled is not None
        assert disabled.status == MCPAppStatus.DISABLED

    async def test_delete_apps_by_server(self, db_session):
        repo = SqlMCPAppRepository(db_session)
        resolver = MagicMock()
        service = MCPAppService(app_repo=repo, resource_resolver=resolver)

        tools = [
            {"name": "t1", "_meta": {"ui": {"resourceUri": "ui://s/a.html"}}},
            {"name": "t2", "_meta": {"ui": {"resourceUri": "ui://s/b.html"}}},
        ]
        await service.detect_apps_from_tools(
            server_id="srv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="server",
            tools=tools,
        )

        count = await service.delete_apps_by_server("srv-1")
        assert count == 2

        listed = await service.list_apps("proj-1")
        assert len(listed) == 0
