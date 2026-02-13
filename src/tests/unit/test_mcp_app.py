"""Unit tests for MCP App domain model and service."""

from datetime import datetime

import pytest

from src.domain.model.mcp.app import (
    MCPApp,
    MCPAppResource,
    MCPAppSource,
    MCPAppStatus,
    MCPAppUIMetadata,
)
from src.domain.model.mcp.tool import MCPToolSchema


@pytest.mark.unit
class TestMCPAppUIMetadata:
    """Tests for MCPAppUIMetadata value object."""

    def test_create_with_defaults(self):
        meta = MCPAppUIMetadata(resource_uri="ui://server/app.html")
        assert meta.resource_uri == "ui://server/app.html"
        assert meta.permissions == []
        assert meta.csp == {}
        assert meta.title is None

    def test_create_with_all_fields(self):
        meta = MCPAppUIMetadata(
            resource_uri="ui://myserver/dashboard.html",
            permissions=["camera", "microphone"],
            csp={"connect-src": ["https://api.example.com"]},
            title="Sales Dashboard",
        )
        assert meta.title == "Sales Dashboard"
        assert len(meta.permissions) == 2

    def test_to_dict(self):
        meta = MCPAppUIMetadata(
            resource_uri="ui://server/app.html",
            title="My App",
        )
        d = meta.to_dict()
        assert d["resourceUri"] == "ui://server/app.html"
        assert d["title"] == "My App"
        # Empty defaults are omitted
        assert "permissions" not in d
        assert "csp" not in d

    def test_from_dict(self):
        data = {
            "resourceUri": "ui://server/app.html",
            "permissions": ["camera"],
            "csp": {},
            "title": "App",
        }
        meta = MCPAppUIMetadata.from_dict(data)
        assert meta.resource_uri == "ui://server/app.html"
        assert meta.permissions == ["camera"]
        assert meta.title == "App"


@pytest.mark.unit
class TestMCPAppResource:
    """Tests for MCPAppResource value object."""

    def test_create_resource(self):
        r = MCPAppResource(
            uri="ui://server/app.html",
            html_content="<h1>Hello</h1>",
            resolved_at=datetime(2026, 1, 1),
            size_bytes=14,
        )
        assert r.uri == "ui://server/app.html"
        assert r.mime_type == "text/html;profile=mcp-app"
        assert r.size_bytes == 14


@pytest.mark.unit
class TestMCPApp:
    """Tests for MCPApp entity."""

    def _make_app(self, **kwargs):
        defaults = {
            "project_id": "proj-1",
            "tenant_id": "tenant-1",
            "server_id": "srv-1",
            "server_name": "my-server",
            "tool_name": "generate_report",
            "ui_metadata": MCPAppUIMetadata(resource_uri="ui://my-server/report.html"),
        }
        defaults.update(kwargs)
        return MCPApp(**defaults)

    def test_create_defaults(self):
        app = self._make_app()
        assert app.id  # UUID generated
        assert app.project_id == "proj-1"
        assert app.source == MCPAppSource.USER_ADDED
        assert app.status == MCPAppStatus.DISCOVERED
        assert app.resource is None
        assert app.error_message is None

    def test_mark_loading(self):
        app = self._make_app()
        app.mark_loading()
        assert app.status == MCPAppStatus.LOADING

    def test_mark_ready(self):
        app = self._make_app()
        resource = MCPAppResource(
            uri="ui://my-server/report.html",
            html_content="<h1>Report</h1>",
            resolved_at=datetime.utcnow(),
            size_bytes=17,
        )
        app.mark_ready(resource)
        assert app.status == MCPAppStatus.READY
        assert app.resource is resource

    def test_mark_error(self):
        app = self._make_app()
        app.mark_error("Connection timed out")
        assert app.status == MCPAppStatus.ERROR
        assert app.error_message == "Connection timed out"

    def test_mark_disabled(self):
        app = self._make_app()
        app.mark_disabled()
        assert app.status == MCPAppStatus.DISABLED

    def test_source_agent_developed(self):
        app = self._make_app(source=MCPAppSource.AGENT_DEVELOPED)
        assert app.source == MCPAppSource.AGENT_DEVELOPED
        assert app.source.value == "agent_developed"

    def test_unique_ids(self):
        app1 = self._make_app()
        app2 = self._make_app()
        assert app1.id != app2.id


@pytest.mark.unit
class TestMCPToolSchemaUI:
    """Tests for MCPToolSchema ui_metadata extension."""

    def test_no_ui_metadata(self):
        schema = MCPToolSchema(name="test_tool")
        assert not schema.has_ui
        assert schema.resource_uri is None

    def test_has_ui_with_resource_uri(self):
        schema = MCPToolSchema(
            name="report_tool",
            ui_metadata={"resourceUri": "ui://server/app.html"},
        )
        assert schema.has_ui
        assert schema.resource_uri == "ui://server/app.html"

    def test_has_ui_non_ui_scheme(self):
        """Any non-empty resourceUri is valid (mcp-app://, https://, etc.)."""
        schema = MCPToolSchema(
            name="web_tool",
            ui_metadata={"resourceUri": "https://example.com/app.html"},
        )
        assert schema.has_ui

    def test_has_ui_mcp_app_scheme(self):
        """mcp-app:// scheme used by @modelcontextprotocol/ext-apps SDK."""
        schema = MCPToolSchema(
            name="mcp_tool",
            ui_metadata={"resourceUri": "mcp-app://hello-app"},
        )
        assert schema.has_ui
        assert schema.resource_uri == "mcp-app://hello-app"

    def test_has_ui_empty_uri(self):
        schema = MCPToolSchema(
            name="tool",
            ui_metadata={"resourceUri": ""},
        )
        assert not schema.has_ui

    def test_to_dict_includes_meta_ui(self):
        schema = MCPToolSchema(
            name="tool",
            description="A tool",
            input_schema={"type": "object"},
            ui_metadata={"resourceUri": "ui://s/a.html", "title": "My App"},
        )
        d = schema.to_dict()
        assert "_meta" in d
        assert d["_meta"]["ui"]["resourceUri"] == "ui://s/a.html"

    def test_to_dict_no_ui(self):
        schema = MCPToolSchema(name="tool", description="A tool")
        d = schema.to_dict()
        assert "_meta" not in d or "ui" not in d.get("_meta", {})

    def test_from_dict_with_meta_ui(self):
        data = {
            "name": "tool",
            "description": "Test",
            "inputSchema": {},
            "_meta": {
                "ui": {
                    "resourceUri": "ui://server/page.html",
                    "title": "Page",
                }
            },
        }
        schema = MCPToolSchema.from_dict(data)
        assert schema.has_ui
        assert schema.resource_uri == "ui://server/page.html"
        assert schema.ui_metadata["title"] == "Page"

    def test_from_dict_without_meta(self):
        data = {"name": "tool", "description": "Test"}
        schema = MCPToolSchema.from_dict(data)
        assert not schema.has_ui
        assert schema.ui_metadata is None


@pytest.mark.unit
class TestMCPAppServiceDetection:
    """Tests for MCPAppService.detect_apps_from_tools logic."""

    async def test_detect_tools_with_ui(self):
        """Test that tools with _meta.ui.resourceUri are detected."""
        from unittest.mock import AsyncMock, MagicMock

        from src.application.services.mcp_app_service import MCPAppService

        mock_repo = MagicMock()
        mock_repo.save = AsyncMock(side_effect=lambda app: app)
        mock_repo.find_by_server_and_tool = AsyncMock(return_value=None)
        mock_resolver = MagicMock()

        service = MCPAppService(app_repo=mock_repo, resource_resolver=mock_resolver)

        tools = [
            {
                "name": "generate_report",
                "description": "Generate sales report",
                "inputSchema": {},
                "_meta": {
                    "ui": {
                        "resourceUri": "ui://my-server/report.html",
                        "title": "Sales Report",
                    }
                },
            },
            {
                "name": "plain_tool",
                "description": "No UI",
                "inputSchema": {},
            },
        ]

        apps = await service.detect_apps_from_tools(
            server_id="srv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="my-server",
            tools=tools,
        )

        assert len(apps) == 1
        assert apps[0].tool_name == "generate_report"
        assert apps[0].ui_metadata.resource_uri == "ui://my-server/report.html"
        assert apps[0].ui_metadata.title == "Sales Report"
        mock_repo.save.assert_called_once()

    async def test_detect_no_ui_tools(self):
        """Test that tools without _meta.ui are ignored."""
        from unittest.mock import AsyncMock, MagicMock

        from src.application.services.mcp_app_service import MCPAppService

        mock_repo = MagicMock()
        mock_repo.save = AsyncMock(side_effect=lambda app: app)
        mock_repo.find_by_server_and_tool = AsyncMock(return_value=None)
        mock_resolver = MagicMock()

        service = MCPAppService(app_repo=mock_repo, resource_resolver=mock_resolver)

        tools = [
            {"name": "tool1", "description": "No UI"},
            {"name": "tool2", "_meta": {"other": True}},
        ]

        apps = await service.detect_apps_from_tools(
            server_id="srv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="server",
            tools=tools,
        )

        assert len(apps) == 0
        mock_repo.save.assert_not_called()

    async def test_detect_skips_existing(self):
        """Test that already-registered apps are not duplicated."""
        from unittest.mock import AsyncMock, MagicMock

        from src.application.services.mcp_app_service import MCPAppService

        existing_app = MCPApp(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_id="srv-1",
            server_name="server",
            tool_name="tool1",
            ui_metadata=MCPAppUIMetadata(resource_uri="ui://server/app.html"),
        )

        mock_repo = MagicMock()
        mock_repo.save = AsyncMock(side_effect=lambda app: app)
        mock_repo.find_by_server_and_tool = AsyncMock(return_value=existing_app)
        mock_resolver = MagicMock()

        service = MCPAppService(app_repo=mock_repo, resource_resolver=mock_resolver)

        tools = [
            {
                "name": "tool1",
                "_meta": {"ui": {"resourceUri": "ui://server/app.html"}},
            },
        ]

        apps = await service.detect_apps_from_tools(
            server_id="srv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="server",
            tools=tools,
        )

        # Should return the existing app, not create a new one
        assert len(apps) == 1
        assert apps[0].id == existing_app.id
        mock_repo.save.assert_not_called()
