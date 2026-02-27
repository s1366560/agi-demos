"""Unit tests for Phase 3 custom tool loading improvements.

Covers diagnostics cache, rescan cache-miss fix, custom_tools_status
tool, and improved error logging with tracebacks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.agent.tools.custom_tool_loader import (
    CustomToolDiagnostic,
    CustomToolLoader,
)
from src.infrastructure.agent.tools.define import (
    ToolInfo,
    clear_registry,
)
from src.infrastructure.agent.tools.result import ToolResult

# Re-use tool file templates from existing tests.
VALID_TOOL_CONTENT = '''"""A valid custom tool."""
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

@tool_define(
    name="test_custom_tool",
    description="A test custom tool",
    parameters={
        "type": "object",
        "properties": {"msg": {"type": "string"}},
        "required": ["msg"],
    },
    permission="read",
    category="custom",
)
async def test_custom_tool(ctx, msg: str) -> ToolResult:
    return ToolResult(output=msg)
'''

SYNTAX_ERROR_CONTENT = '''"""File with syntax error."""
def broken_function(
    return "missing colon"
'''

_STATE_MODULE = "src.infrastructure.agent.state.agent_worker_state"
_LOADER_MODULE = "src.infrastructure.agent.tools.custom_tool_loader"


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Ensure tool registry is clean before/after each test."""
    clear_registry()
    yield  # type: ignore[misc]
    clear_registry()


# ------------------------------------------------------------------
# Class 1: DiagnosticsCache
# ------------------------------------------------------------------


@pytest.mark.unit
class TestCustomToolDiagnosticsCache:
    """Tests for the diagnostics cache in agent_worker_state."""

    @patch(f"{_STATE_MODULE}._custom_tool_diagnostics", new_callable=dict)
    def test_get_custom_tool_diagnostics_empty(
        self,
        mock_diags: dict[str, list[Any]],
    ) -> None:
        """Empty cache returns empty list."""
        from src.infrastructure.agent.state.agent_worker_state import (
            get_custom_tool_diagnostics,
        )

        # Act
        result = get_custom_tool_diagnostics("proj1")

        # Assert
        assert result == []

    @patch(f"{_STATE_MODULE}._custom_tool_diagnostics", new_callable=dict)
    def test_get_custom_tool_diagnostics_returns_stored(
        self,
        mock_diags: dict[str, list[Any]],
    ) -> None:
        """Stored diagnostics are returned correctly."""
        from src.infrastructure.agent.state.agent_worker_state import (
            get_custom_tool_diagnostics,
        )

        # Arrange
        diag = CustomToolDiagnostic(
            file_path="tool.py",
            code="tools_loaded",
            message="ok",
            level="info",
        )
        mock_diags["proj1"] = [diag]

        # Act
        result = get_custom_tool_diagnostics("proj1")

        # Assert
        assert len(result) == 1
        assert result[0].code == "tools_loaded"

    @patch(f"{_STATE_MODULE}._custom_tool_diagnostics", new_callable=dict)
    def test_get_custom_tool_diagnostics_returns_copy(
        self,
        mock_diags: dict[str, list[Any]],
    ) -> None:
        """Returned list is a copy; mutating it does not affect cache."""
        from src.infrastructure.agent.state.agent_worker_state import (
            get_custom_tool_diagnostics,
        )

        # Arrange
        diag = CustomToolDiagnostic(
            file_path="a.py",
            code="ok",
            message="loaded",
            level="info",
        )
        mock_diags["proj1"] = [diag]

        # Act
        result = get_custom_tool_diagnostics("proj1")
        result.clear()

        # Assert -- original cache is untouched
        assert len(mock_diags["proj1"]) == 1

    @patch(f"{_STATE_MODULE}._tools_cache", new_callable=dict)
    @patch(f"{_STATE_MODULE}._custom_tool_diagnostics", new_callable=dict)
    def test_invalidate_tools_cache_clears_diagnostics_for_project(
        self,
        mock_diags: dict[str, list[Any]],
        mock_cache: dict[str, Any],
    ) -> None:
        """Invalidating one project clears only that project's diagnostics."""
        from src.infrastructure.agent.state.agent_worker_state import (
            invalidate_tools_cache,
        )

        # Arrange
        mock_diags["proj1"] = [
            CustomToolDiagnostic("a.py", "ok", "loaded", "info"),
        ]
        mock_diags["proj2"] = [
            CustomToolDiagnostic("b.py", "ok", "loaded", "info"),
        ]
        mock_cache["proj1"] = {"t": "val"}

        # Act
        invalidate_tools_cache("proj1")

        # Assert
        assert "proj1" not in mock_diags
        assert "proj2" in mock_diags
        assert len(mock_diags["proj2"]) == 1

    @patch(f"{_STATE_MODULE}._tools_cache", new_callable=dict)
    @patch(f"{_STATE_MODULE}._custom_tool_diagnostics", new_callable=dict)
    def test_invalidate_tools_cache_clears_all_diagnostics(
        self,
        mock_diags: dict[str, list[Any]],
        mock_cache: dict[str, Any],
    ) -> None:
        """Passing None clears diagnostics for ALL projects."""
        from src.infrastructure.agent.state.agent_worker_state import (
            invalidate_tools_cache,
        )

        # Arrange
        mock_diags["proj1"] = [
            CustomToolDiagnostic("a.py", "ok", "m1", "info"),
        ]
        mock_diags["proj2"] = [
            CustomToolDiagnostic("b.py", "ok", "m2", "info"),
        ]
        mock_cache["proj1"] = {}
        mock_cache["proj2"] = {}

        # Act
        invalidate_tools_cache(None)

        # Assert
        assert len(mock_diags) == 0
        assert len(mock_cache) == 0


# ------------------------------------------------------------------
# Class 2: custom_tools_status tool
# ------------------------------------------------------------------


@pytest.mark.unit
class TestCustomToolsStatusTool:
    """Tests for the custom_tools_status diagnostic tool."""

    @patch(
        f"{_STATE_MODULE}.get_custom_tool_diagnostics",
        return_value=[],
    )
    async def test_status_tool_no_diagnostics(
        self,
        mock_get: MagicMock,
    ) -> None:
        """Empty diagnostics produce 'no diagnostics' message."""
        from src.infrastructure.agent.tools.custom_tool_status import (
            custom_tools_status,
        )

        # Arrange
        ctx = MagicMock()
        ctx.project_id = "proj1"

        # Act
        result: ToolResult = await custom_tools_status.execute(ctx)

        # Assert
        assert "No custom tools diagnostics" in result.output

    @patch(f"{_STATE_MODULE}.get_custom_tool_diagnostics")
    async def test_status_tool_with_errors_warnings_loaded(
        self,
        mock_get: MagicMock,
    ) -> None:
        """Output formats errors, warnings, and loaded sections."""
        from src.infrastructure.agent.tools.custom_tool_status import (
            custom_tools_status,
        )

        # Arrange
        mock_get.return_value = [
            CustomToolDiagnostic("e.py", "import_failed", "boom", "error"),
            CustomToolDiagnostic("w.py", "no_tools_found", "none", "warning"),
            CustomToolDiagnostic("i.py", "tools_loaded", "ok", "info"),
        ]
        ctx = MagicMock()
        ctx.project_id = "proj1"

        # Act
        result: ToolResult = await custom_tools_status.execute(ctx)
        output = result.output

        # Assert
        assert "1 loaded" in output
        assert "1 errors" in output
        assert "1 warnings" in output
        assert "ERRORS:" in output
        assert "WARNINGS:" in output
        assert "LOADED:" in output

    def test_status_tool_is_registered(self) -> None:
        """custom_tools_status is a ToolInfo with correct attributes."""
        from src.infrastructure.agent.tools.custom_tool_status import (
            custom_tools_status,
        )

        assert isinstance(custom_tools_status, ToolInfo)
        assert custom_tools_status.name == "custom_tools_status"
        assert callable(custom_tools_status.execute)
        assert custom_tools_status.category == "diagnostics"


# ------------------------------------------------------------------
# Class 3: Traceback in error logging
# ------------------------------------------------------------------


@pytest.mark.unit
class TestCustomToolLoaderTraceback:
    """Tests for improved error logging with traceback."""

    def test_load_file_error_includes_traceback(
        self,
        tmp_path: Path,
    ) -> None:
        """Syntax error diagnostic message contains traceback info."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "broken.py").write_text(SYNTAX_ERROR_CONTENT)
        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        _tools, diagnostics = loader.load_all()

        # Assert
        error_diags = [d for d in diagnostics if d.level == "error"]
        assert len(error_diags) == 1
        assert "traceback" in error_diags[0].message.lower()

    @patch(f"{_LOADER_MODULE}.logger")
    def test_load_file_error_logged_at_error_level(
        self,
        mock_logger: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Import failure is logged via logger.error."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "broken.py").write_text(SYNTAX_ERROR_CONTENT)
        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        loader.load_all()

        # Assert
        mock_logger.error.assert_called()


# ------------------------------------------------------------------
# Class 4: Rescan cache-miss fix
# ------------------------------------------------------------------


@pytest.mark.unit
class TestRescanCacheMiss:
    """Tests for the rescan cache-miss fix in agent_worker_state."""

    @patch(f"{_LOADER_MODULE}.load_custom_tools")
    @patch(f"{_STATE_MODULE}.resolve_project_base_path")
    @patch(f"{_STATE_MODULE}._custom_tool_diagnostics", new_callable=dict)
    @patch(f"{_STATE_MODULE}._tools_cache", new_callable=dict)
    def test_rescan_no_cache_still_records_diagnostics(
        self,
        mock_cache: dict[str, Any],
        mock_diags: dict[str, list[Any]],
        mock_resolve: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        """No cache entry: rescan still stores diagnostics."""
        from src.infrastructure.agent.state.agent_worker_state import (
            rescan_custom_tools_for_project,
        )

        # Arrange -- no entry in _tools_cache for "proj1"
        diag = CustomToolDiagnostic("t.py", "tools_loaded", "ok", "info")
        mock_resolve.return_value = Path("/fake")
        mock_load.return_value = ({"my_tool": MagicMock()}, [diag])

        # Act
        count = rescan_custom_tools_for_project("proj1")

        # Assert
        assert count == 1
        assert "proj1" in mock_diags
        assert len(mock_diags["proj1"]) == 1
        assert mock_diags["proj1"][0].code == "tools_loaded"

    @patch(f"{_LOADER_MODULE}.load_custom_tools")
    @patch(f"{_STATE_MODULE}.resolve_project_base_path")
    @patch(f"{_STATE_MODULE}._custom_tool_diagnostics", new_callable=dict)
    @patch(f"{_STATE_MODULE}._tools_cache", new_callable=dict)
    def test_rescan_with_cache_stores_diagnostics(
        self,
        mock_cache: dict[str, Any],
        mock_diags: dict[str, list[Any]],
        mock_resolve: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        """With cache entry: diagnostics are stored AND tools merged."""
        from src.infrastructure.agent.state.agent_worker_state import (
            rescan_custom_tools_for_project,
        )

        # Arrange -- cache has an existing entry
        mock_cache["proj1"] = {"existing_tool": MagicMock()}
        diag = CustomToolDiagnostic("t.py", "tools_loaded", "ok", "info")
        mock_resolve.return_value = Path("/fake")
        tool_mock = MagicMock(spec=ToolInfo)
        mock_load.return_value = ({"new_tool": tool_mock}, [diag])

        # Act
        count = rescan_custom_tools_for_project("proj1")

        # Assert
        assert count == 1
        assert "proj1" in mock_diags
        assert mock_diags["proj1"][0].code == "tools_loaded"
        # Verify tool was merged into cache
        assert "new_tool" in mock_cache["proj1"]
