"""Unit tests for sandbox_plugin_tool_wrapper."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.plugins.sandbox_deps.models import (
    InstallResult,
    RuntimeDependencies,
)
from src.infrastructure.agent.plugins.sandbox_deps.sandbox_plugin_tool_wrapper import (
    _extract_error_text,
    _extract_success_text,
    create_sandbox_plugin_tool,
)
from src.infrastructure.agent.tools.context import ToolContext


def _make_ctx() -> MagicMock:
    """Create a minimal mock ToolContext."""
    return MagicMock(spec=ToolContext)


def _make_deps() -> RuntimeDependencies:
    """Create basic RuntimeDependencies."""
    return RuntimeDependencies(pip_packages=("pandas",))


def _make_tool(
    orchestrator: AsyncMock | None = None,
    sandbox_port: AsyncMock | None = None,
    deps: RuntimeDependencies | None = None,
    plugin_id: str = "plug-1",
    tool_name: str = "my_tool",
    description: str = "A test tool",
    parameters: dict[str, Any] | None = None,
    sandbox_id: str = "sbx-1",
    project_id: str = "proj-1",
    permission: str | None = "execute",
    category: str = "plugin",
) -> Any:
    """Helper to create a sandbox plugin tool."""
    return create_sandbox_plugin_tool(
        plugin_id=plugin_id,
        tool_name=tool_name,
        description=description,
        parameters=parameters or {"type": "object", "properties": {}},
        sandbox_id=sandbox_id,
        project_id=project_id,
        sandbox_port=sandbox_port or AsyncMock(),
        orchestrator=orchestrator or AsyncMock(),
        dependencies=deps or _make_deps(),
        permission=permission,
        category=category,
    )


@pytest.mark.unit
class TestCreateSandboxPluginTool:
    """Tests for the create_sandbox_plugin_tool factory."""

    async def test_returns_valid_tool_info(self) -> None:
        """create_sandbox_plugin_tool returns a ToolInfo."""
        from src.infrastructure.agent.tools.define import ToolInfo

        tool = _make_tool()

        assert isinstance(tool, ToolInfo)
        assert tool.name == "my_tool"
        assert tool.description == "A test tool"
        assert callable(tool.execute)

    async def test_tool_has_plugin_sandbox_tags(self) -> None:
        """ToolInfo has tags frozenset({'plugin', 'sandbox'})."""
        tool = _make_tool()

        assert tool.tags == frozenset({"plugin", "sandbox"})

    async def test_tool_has_dependencies_field(self) -> None:
        """ToolInfo carries the dependencies manifest."""
        deps = _make_deps()
        tool = _make_tool(deps=deps)

        assert tool.dependencies is deps

    async def test_permission_and_category_propagated(self) -> None:
        """Permission and category are set on ToolInfo."""
        tool = _make_tool(permission="admin", category="custom")

        assert tool.permission == "admin"
        assert tool.category == "custom"


@pytest.mark.unit
class TestExecuteDepInstallation:
    """Tests for dependency installation during execute."""

    async def test_first_call_installs_deps_then_delegates(
        self,
    ) -> None:
        """First call triggers dep install, then calls sandbox."""
        orchestrator = AsyncMock()
        orchestrator.ensure_dependencies = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
                installed_packages=("pandas",),
            )
        )

        sandbox_port = AsyncMock()
        sandbox_port.call_tool = AsyncMock(
            return_value={
                "content": [{"text": "result data"}],
            }
        )

        tool = _make_tool(
            orchestrator=orchestrator,
            sandbox_port=sandbox_port,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx, arg1="val1")

        assert not result.is_error
        assert result.output == "result data"
        orchestrator.ensure_dependencies.assert_called_once()
        sandbox_port.call_tool.assert_called_once_with("sbx-1", "my_tool", {"arg1": "val1"})

    async def test_second_call_skips_dep_install(self) -> None:
        """Second call skips dependency installation."""
        orchestrator = AsyncMock()
        orchestrator.ensure_dependencies = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
                installed_packages=("pandas",),
            )
        )

        sandbox_port = AsyncMock()
        sandbox_port.call_tool = AsyncMock(
            return_value={
                "content": [{"text": "ok"}],
            }
        )

        tool = _make_tool(
            orchestrator=orchestrator,
            sandbox_port=sandbox_port,
        )

        ctx = _make_ctx()
        # First call
        await tool.execute(ctx)
        # Second call
        await tool.execute(ctx)

        # ensure_dependencies called only once
        assert orchestrator.ensure_dependencies.call_count == 1
        # sandbox call_tool called twice
        assert sandbox_port.call_tool.call_count == 2

    async def test_dep_install_failure_returns_error(self) -> None:
        """When dep install fails, return error ToolResult."""
        orchestrator = AsyncMock()
        orchestrator.ensure_dependencies = AsyncMock(
            return_value=InstallResult(
                success=False,
                plugin_id="plug-1",
                errors=("install failed",),
            )
        )

        sandbox_port = AsyncMock()

        tool = _make_tool(
            orchestrator=orchestrator,
            sandbox_port=sandbox_port,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx)

        assert result.is_error is True
        assert "install failed" in result.output
        sandbox_port.call_tool.assert_not_called()


@pytest.mark.unit
class TestExecuteSandboxCall:
    """Tests for sandbox call_tool delegation."""

    async def test_sandbox_call_error_is_error_flag(self) -> None:
        """When sandbox returns isError=true, result is error."""
        orchestrator = AsyncMock()
        orchestrator.ensure_dependencies = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
            )
        )

        sandbox_port = AsyncMock()
        sandbox_port.call_tool = AsyncMock(
            return_value={
                "isError": True,
                "content": [{"text": "sandbox error msg"}],
            }
        )

        tool = _make_tool(
            orchestrator=orchestrator,
            sandbox_port=sandbox_port,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx)

        assert result.is_error is True
        assert "sandbox error msg" in result.output

    async def test_sandbox_call_error_is_error_key(self) -> None:
        """When sandbox returns is_error=true, result is error."""
        orchestrator = AsyncMock()
        orchestrator.ensure_dependencies = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
            )
        )

        sandbox_port = AsyncMock()
        sandbox_port.call_tool = AsyncMock(
            return_value={
                "is_error": True,
                "content": [{"text": "snake_case error"}],
            }
        )

        tool = _make_tool(
            orchestrator=orchestrator,
            sandbox_port=sandbox_port,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx)

        assert result.is_error is True

    async def test_sandbox_call_success(self) -> None:
        """Successful sandbox call returns output."""
        orchestrator = AsyncMock()
        orchestrator.ensure_dependencies = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
            )
        )

        sandbox_port = AsyncMock()
        sandbox_port.call_tool = AsyncMock(
            return_value={
                "content": [{"text": "hello world"}],
            }
        )

        tool = _make_tool(
            orchestrator=orchestrator,
            sandbox_port=sandbox_port,
        )

        ctx = _make_ctx()
        result = await tool.execute(ctx)

        assert result.is_error is False
        assert result.output == "hello world"


@pytest.mark.unit
class TestExtractErrorText:
    """Tests for _extract_error_text helper."""

    async def test_extracts_text_from_content(self) -> None:
        """Extracts text from content[0]['text']."""
        result: dict[str, Any] = {
            "content": [{"text": "error details"}],
        }
        assert _extract_error_text(result) == "error details"

    async def test_non_dict_content_item(self) -> None:
        """Handles non-dict content items."""
        result: dict[str, Any] = {
            "content": ["plain string error"],
        }
        assert _extract_error_text(result) == "plain string error"

    async def test_empty_content_fallback(self) -> None:
        """Falls back when content is empty."""
        result: dict[str, Any] = {"content": []}
        text = _extract_error_text(result)
        assert "Raw result" in text

    async def test_missing_content_fallback(self) -> None:
        """Falls back when content key is missing."""
        result: dict[str, Any] = {}
        text = _extract_error_text(result)
        assert "Raw result" in text

    async def test_empty_text_fallback(self) -> None:
        """Falls back when text field is empty string."""
        result: dict[str, Any] = {
            "content": [{"text": ""}],
        }
        text = _extract_error_text(result)
        assert "Raw result" in text


@pytest.mark.unit
class TestExtractSuccessText:
    """Tests for _extract_success_text helper."""

    async def test_extracts_text_from_content(self) -> None:
        """Extracts text from content[0]['text']."""
        result: dict[str, Any] = {
            "content": [{"text": "output data"}],
        }
        assert _extract_success_text(result) == "output data"

    async def test_non_dict_content_item(self) -> None:
        """Handles non-dict content items."""
        result: dict[str, Any] = {
            "content": ["plain output"],
        }
        assert _extract_success_text(result) == "plain output"

    async def test_empty_content_returns_success(self) -> None:
        """Returns 'Success' when content is empty."""
        result: dict[str, Any] = {"content": []}
        assert _extract_success_text(result) == "Success"

    async def test_missing_content_returns_success(self) -> None:
        """Returns 'Success' when content key is missing."""
        result: dict[str, Any] = {}
        assert _extract_success_text(result) == "Success"
