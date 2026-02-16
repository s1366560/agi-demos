"""Tests for MCP Server development templates.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that MCP Server templates provide standardized
starting points for common server patterns.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMCPServerTemplates:
    """Test MCP Server template functionality."""

    def test_template_tool_exists(self):
        """
        RED Test: Verify that CreateMCPServerFromTemplateTool class exists.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            CreateMCPServerFromTemplateTool,
        )

        assert CreateMCPServerFromTemplateTool is not None

    def test_list_available_templates(self):
        """
        Test that available templates can be listed.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            CreateMCPServerFromTemplateTool,
            list_available_templates,
        )

        templates = list_available_templates()

        # Should have at least a few templates
        assert len(templates) >= 3

        # Each template should have name and description
        for template in templates:
            assert "name" in template
            assert "description" in template

    def test_web_dashboard_template_exists(self):
        """
        Test that web-dashboard template exists.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            get_template_by_name,
        )

        template = get_template_by_name("web-dashboard")

        assert template is not None
        assert template["name"] == "web-dashboard"
        assert "files" in template
        assert "dependencies" in template

    def test_api_wrapper_template_exists(self):
        """
        Test that api-wrapper template exists.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            get_template_by_name,
        )

        template = get_template_by_name("api-wrapper")

        assert template is not None
        assert template["name"] == "api-wrapper"
        assert "files" in template

    def test_data_processor_template_exists(self):
        """
        Test that data-processor template exists.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            get_template_by_name,
        )

        template = get_template_by_name("data-processor")

        assert template is not None
        assert template["name"] == "data-processor"

    def test_get_nonexistent_template_returns_none(self):
        """
        Test that getting nonexistent template returns None.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            get_template_by_name,
        )

        template = get_template_by_name("nonexistent-template")

        assert template is None

    def test_template_files_have_content(self):
        """
        Test that template files have actual content.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            get_template_by_name,
        )

        template = get_template_by_name("web-dashboard")
        files = template["files"]

        # Each file should have a path and content
        for file_info in files:
            assert "path" in file_info
            assert "content" in file_info
            assert len(file_info["content"]) > 0  # Non-empty content


class TestCreateMCPServerFromTemplateTool:
    """Test the CreateMCPServerFromTemplateTool functionality."""

    @pytest.mark.asyncio
    async def test_tool_has_name_and_description(self):
        """
        Test that tool has proper name and description.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            CreateMCPServerFromTemplateTool,
        )

        mock_adapter = AsyncMock()
        tool = CreateMCPServerFromTemplateTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            workspace_path="/workspace",
        )

        assert tool.name == "create_mcp_server_from_template"
        assert "template" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_create_from_template_writes_files(self):
        """
        Test that creating from template writes files to sandbox.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            CreateMCPServerFromTemplateTool,
        )

        mock_adapter = AsyncMock()

        # Track file writes
        written_files = []

        async def track_write(tool_name, arguments, **kwargs):
            if tool_name == "write":
                path = arguments.get("path", "")
                content = arguments.get("content", "")
                written_files.append({"path": path, "content": content})
                return {"content": [{"type": "text", "text": f"Wrote {path}"}]}
            return {"content": [{"type": "text", "text": "{}"}]}

        mock_adapter.call_tool = track_write

        tool = CreateMCPServerFromTemplateTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            workspace_path="/workspace",
        )

        result = await tool.execute(
            template="web-dashboard",
            server_name="my-dashboard",
        )

        # Should have written some files
        assert len(written_files) >= 1

        # At least one file should be in the server directory
        server_files = [f for f in written_files if "my-dashboard" in f["path"]]
        assert len(server_files) >= 1

    @pytest.mark.asyncio
    async def test_create_from_template_installs_dependencies(self):
        """
        Test that creating from template installs dependencies.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            CreateMCPServerFromTemplateTool,
        )

        mock_adapter = AsyncMock()

        # Track bash commands
        bash_commands = []

        async def track_bash(tool_name, arguments, **kwargs):
            if tool_name == "bash":
                command = arguments.get("command", "")
                bash_commands.append(command)
                return {"content": [{"type": "text", "text": "Done"}]}
            if tool_name == "write":
                return {"content": [{"type": "text", "text": "Written"}]}
            return {"content": [{"type": "text", "text": "{}"}]}

        mock_adapter.call_tool = track_bash

        tool = CreateMCPServerFromTemplateTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            workspace_path="/workspace",
        )

        await tool.execute(
            template="web-dashboard",
            server_name="my-server",
            install_deps=True,
        )

        # Should have run install command
        install_commands = [c for c in bash_commands if "install" in c.lower() or "pip" in c or "npm" in c]
        assert len(install_commands) >= 1

    @pytest.mark.asyncio
    async def test_create_from_template_validates_template_name(self):
        """
        Test that tool validates template name.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            CreateMCPServerFromTemplateTool,
        )

        mock_adapter = AsyncMock()
        tool = CreateMCPServerFromTemplateTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            workspace_path="/workspace",
        )

        result = await tool.execute(
            template="invalid-template-name",
            server_name="my-server",
        )

        # Should return error message
        assert "error" in result.lower() or "not found" in result.lower() or "invalid" in result.lower()

    @pytest.mark.asyncio
    async def test_create_from_template_customizes_server_name(self):
        """
        Test that template is customized with server name.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            CreateMCPServerFromTemplateTool,
        )

        mock_adapter = AsyncMock()

        written_files = []

        async def track_write(tool_name, arguments, **kwargs):
            if tool_name == "write":
                path = arguments.get("path", "")
                content = arguments.get("content", "")
                written_files.append({"path": path, "content": content})
                return {"content": [{"type": "text", "text": f"Wrote {path}"}]}
            return {"content": [{"type": "text", "text": "{}"}]}

        mock_adapter.call_tool = track_write

        tool = CreateMCPServerFromTemplateTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            workspace_path="/workspace",
        )

        await tool.execute(
            template="api-wrapper",
            server_name="my-custom-api",
        )

        # Check that content was customized
        all_content = " ".join(f["content"] for f in written_files)

        # Server name should appear in the generated code
        assert "my-custom-api" in all_content or "my_custom_api" in all_content


class TestTemplateRendering:
    """Test template rendering functionality."""

    def test_render_template_substitutes_variables(self):
        """
        Test that render_template substitutes variables.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            render_template_content,
        )

        template = "Server name: {{server_name}}, Description: {{description}}"
        variables = {"server_name": "my-server", "description": "My API"}

        result = render_template_content(template, variables)

        assert "my-server" in result
        assert "My API" in result
        assert "{{" not in result  # No unrendered placeholders

    def test_render_template_handles_missing_variables(self):
        """
        Test that render_template handles missing variables gracefully.
        """
        from src.infrastructure.agent.tools.mcp_server_templates import (
            render_template_content,
        )

        template = "Server: {{server_name}}, Missing: {{missing_var}}"
        variables = {"server_name": "my-server"}

        result = render_template_content(template, variables)

        # Should substitute known variable
        assert "my-server" in result
        # Missing variable should be empty or kept as placeholder
        # (implementation choice, just verify it doesn't crash)
        assert result is not None
