"""Tests for MCP Server development templates.

Tests the @tool_define-based create_mcp_server_from_template_tool and its
helper functions: list_available_templates, get_template_by_name,
render_template_content, and configure_create_mcp_server_from_template_tool.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.mcp_server_templates import (
    configure_create_mcp_server_from_template_tool,
    create_mcp_server_from_template_tool,
    get_template_by_name,
    list_available_templates,
    render_template_content,
)
from src.infrastructure.agent.tools.result import ToolResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_sandbox_adapter() -> AsyncMock:
    """Provide a mock SandboxPort adapter."""
    adapter = AsyncMock()
    adapter.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "OK"}]})
    return adapter


@pytest.fixture()
def tool_ctx() -> ToolContext:
    """Provide a minimal ToolContext for tool invocation."""
    return ToolContext(
        session_id="sess-1",
        message_id="msg-1",
        call_id="call-1",
        agent_name="test-agent",
        conversation_id="conv-1",
    )


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """Reset module-level DI references between tests."""
    import src.infrastructure.agent.tools.mcp_server_templates as mod

    mod._template_sandbox_adapter = None
    mod._template_sandbox_id = None
    mod._template_workspace_path = "/workspace"


# ===========================================================================
# TestListAvailableTemplates
# ===========================================================================


class TestListAvailableTemplates:
    """Tests for list_available_templates()."""

    def test_returns_at_least_three_templates(self) -> None:
        """Should have at least web-dashboard, api-wrapper, data-processor."""
        templates = list_available_templates()
        assert len(templates) >= 3

    def test_each_template_has_name_and_description(self) -> None:
        """Every entry must carry name and description keys."""
        for template in list_available_templates():
            assert "name" in template
            assert "description" in template


# ===========================================================================
# TestGetTemplateByName
# ===========================================================================


class TestGetTemplateByName:
    """Tests for get_template_by_name()."""

    def test_web_dashboard_template_exists(self) -> None:
        """web-dashboard template is available with files and deps."""
        template = get_template_by_name("web-dashboard")
        assert template is not None
        assert template["name"] == "web-dashboard"
        assert "files" in template
        assert "dependencies" in template

    def test_api_wrapper_template_exists(self) -> None:
        """api-wrapper template is available."""
        template = get_template_by_name("api-wrapper")
        assert template is not None
        assert template["name"] == "api-wrapper"
        assert "files" in template

    def test_data_processor_template_exists(self) -> None:
        """data-processor template is available."""
        template = get_template_by_name("data-processor")
        assert template is not None
        assert template["name"] == "data-processor"

    def test_nonexistent_template_returns_none(self) -> None:
        """Unknown template name returns None."""
        assert get_template_by_name("nonexistent-template") is None

    def test_template_files_have_content(self) -> None:
        """Template files contain path and non-empty content."""
        template = get_template_by_name("web-dashboard")
        assert template is not None
        for file_info in template["files"]:
            assert "path" in file_info
            assert "content" in file_info
            assert len(file_info["content"]) > 0


# ===========================================================================
# TestRenderTemplateContent
# ===========================================================================


class TestRenderTemplateContent:
    """Tests for render_template_content()."""

    def test_substitutes_variables(self) -> None:
        """Known variables are replaced in template text."""
        template = "Server name: {{server_name}}, Description: {{description}}"
        variables = {"server_name": "my-server", "description": "My API"}
        result = render_template_content(template, variables)

        assert "my-server" in result
        assert "My API" in result
        assert "{{server_name}}" not in result
        assert "{{description}}" not in result

    def test_handles_missing_variables(self) -> None:
        """Missing variables do not crash; known ones still substitute."""
        template = "Server: {{server_name}}, Missing: {{missing_var}}"
        variables = {"server_name": "my-server"}
        result = render_template_content(template, variables)

        assert "my-server" in result
        assert result is not None


# ===========================================================================
# TestToolInfo
# ===========================================================================


class TestToolInfo:
    """Tests for the ToolInfo returned by @tool_define."""

    def test_tool_has_correct_name(self) -> None:
        """ToolInfo name matches the @tool_define name."""
        assert create_mcp_server_from_template_tool.name == "create_mcp_server_from_template"

    def test_tool_description_mentions_template(self) -> None:
        """ToolInfo description references templates."""
        desc = create_mcp_server_from_template_tool.description.lower()
        assert "template" in desc


# ===========================================================================
# TestCreateMCPServerFromTemplateTool (integration-style with mocks)
# ===========================================================================


class TestCreateMCPServerFromTemplateTool:
    """Tests for the create_mcp_server_from_template_tool execution."""

    async def test_returns_error_when_sandbox_not_configured(self, tool_ctx: ToolContext) -> None:
        """Without configure_*, returns error about sandbox not available."""
        result: ToolResult = await create_mcp_server_from_template_tool.execute(
            tool_ctx,
            template="web-dashboard",
            server_name="my-server",
        )
        assert result.is_error is True
        assert "sandbox" in result.output.lower() or "error" in result.output.lower()

    async def test_returns_error_for_invalid_template(
        self, mock_sandbox_adapter: AsyncMock, tool_ctx: ToolContext
    ) -> None:
        """Invalid template name returns error."""
        configure_create_mcp_server_from_template_tool(
            sandbox_adapter=mock_sandbox_adapter,
            sandbox_id="sandbox-1",
        )
        result: ToolResult = await create_mcp_server_from_template_tool.execute(
            tool_ctx,
            template="invalid-template-name",
            server_name="my-server",
        )
        assert result.is_error is True
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    async def test_returns_error_for_invalid_server_name(
        self, mock_sandbox_adapter: AsyncMock, tool_ctx: ToolContext
    ) -> None:
        """Server names with uppercase or invalid chars return error."""
        configure_create_mcp_server_from_template_tool(
            sandbox_adapter=mock_sandbox_adapter,
            sandbox_id="sandbox-1",
        )
        result: ToolResult = await create_mcp_server_from_template_tool.execute(
            tool_ctx,
            template="web-dashboard",
            server_name="INVALID_Name",
        )
        assert result.is_error is True
        assert "invalid" in result.output.lower() or "error" in result.output.lower()

    async def test_creates_files_from_template(
        self, mock_sandbox_adapter: AsyncMock, tool_ctx: ToolContext
    ) -> None:
        """Creating from template writes files to sandbox."""
        written_files: list[dict[str, str]] = []

        async def track_write(
            tool_name: str,
            arguments: dict[str, str],
            **kwargs: object,
        ) -> dict[str, list[dict[str, str]]]:
            if tool_name == "write":
                written_files.append(
                    {
                        "path": arguments.get("path", ""),
                        "content": arguments.get("content", ""),
                    }
                )
            return {"content": [{"type": "text", "text": "OK"}]}

        mock_sandbox_adapter.call_tool = track_write

        configure_create_mcp_server_from_template_tool(
            sandbox_adapter=mock_sandbox_adapter,
            sandbox_id="sandbox-1",
        )
        result: ToolResult = await create_mcp_server_from_template_tool.execute(
            tool_ctx,
            template="web-dashboard",
            server_name="my-dashboard",
            install_deps=False,
        )

        assert result.is_error is False
        assert len(written_files) >= 1
        server_files = [f for f in written_files if "my-dashboard" in f["path"]]
        assert len(server_files) >= 1

    async def test_installs_dependencies(
        self, mock_sandbox_adapter: AsyncMock, tool_ctx: ToolContext
    ) -> None:
        """With install_deps=True, runs install command via bash."""
        bash_commands: list[str] = []

        async def track_bash(
            tool_name: str,
            arguments: dict[str, str],
            **kwargs: object,
        ) -> dict[str, list[dict[str, str]]]:
            if tool_name == "bash":
                bash_commands.append(arguments.get("command", ""))
            return {"content": [{"type": "text", "text": "Done"}]}

        mock_sandbox_adapter.call_tool = track_bash

        configure_create_mcp_server_from_template_tool(
            sandbox_adapter=mock_sandbox_adapter,
            sandbox_id="sandbox-1",
        )
        await create_mcp_server_from_template_tool.execute(
            tool_ctx,
            template="web-dashboard",
            server_name="my-server",
            install_deps=True,
        )

        install_commands = [c for c in bash_commands if "install" in c.lower() or "pip" in c]
        assert len(install_commands) >= 1

    async def test_customizes_server_name_in_content(
        self, mock_sandbox_adapter: AsyncMock, tool_ctx: ToolContext
    ) -> None:
        """Server name appears in generated file content."""
        written_files: list[dict[str, str]] = []

        async def track_write(
            tool_name: str,
            arguments: dict[str, str],
            **kwargs: object,
        ) -> dict[str, list[dict[str, str]]]:
            if tool_name == "write":
                written_files.append(
                    {
                        "path": arguments.get("path", ""),
                        "content": arguments.get("content", ""),
                    }
                )
            return {"content": [{"type": "text", "text": "OK"}]}

        mock_sandbox_adapter.call_tool = track_write

        configure_create_mcp_server_from_template_tool(
            sandbox_adapter=mock_sandbox_adapter,
            sandbox_id="sandbox-1",
        )
        await create_mcp_server_from_template_tool.execute(
            tool_ctx,
            template="api-wrapper",
            server_name="my-custom-api",
            install_deps=False,
        )

        all_content = " ".join(f["content"] for f in written_files)
        assert "my-custom-api" in all_content or "my_custom_api" in all_content

    async def test_success_output_contains_metadata(
        self, mock_sandbox_adapter: AsyncMock, tool_ctx: ToolContext
    ) -> None:
        """Successful creation returns ToolResult with metadata."""
        configure_create_mcp_server_from_template_tool(
            sandbox_adapter=mock_sandbox_adapter,
            sandbox_id="sandbox-1",
        )
        result: ToolResult = await create_mcp_server_from_template_tool.execute(
            tool_ctx,
            template="data-processor",
            server_name="my-processor",
            install_deps=False,
        )

        assert result.is_error is False
        assert "my-processor" in result.output
        assert "data-processor" in result.output
        assert result.metadata is not None
        assert result.metadata["template"] == "data-processor"
        assert result.metadata["server_name"] == "my-processor"
