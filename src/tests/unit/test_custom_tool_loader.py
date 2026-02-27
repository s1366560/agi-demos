"""Unit tests for CustomToolLoader."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.agent.tools.custom_tool_loader import (
    CustomToolLoader,
    load_custom_tools,
)
from src.infrastructure.agent.tools.define import (
    _TOOL_REGISTRY,
    ToolInfo,
    clear_registry,
)
from src.infrastructure.agent.tools.hooks import ToolHookRegistry

# Tool file templates
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

ANOTHER_VALID_TOOL = '''"""Another valid custom tool."""
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

@tool_define(
    name="another_tool",
    description="Another test tool",
    parameters={
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
    },
    permission="read",
    category="custom",
)
async def another_tool(ctx, value: float) -> ToolResult:
    return ToolResult(output=str(value))
'''

DUPLICATE_TOOL_NAME = '''"""Tool with duplicate name."""
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

@tool_define(
    name="test_custom_tool",
    description="Duplicate name",
    parameters={"type": "object", "properties": {}, "required": []},
    permission="read",
    category="custom",
)
async def duplicate_tool(ctx) -> ToolResult:
    return ToolResult(output="duplicate")
'''

NO_TOOL_CONTENT = '''"""File with no tools."""
def helper_function():
    return "not a tool"
'''

SYNTAX_ERROR_CONTENT = '''"""File with syntax error."""
def broken_function(
    return "missing colon"
'''


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Ensure tool registry is clean before/after each test."""
    clear_registry()
    yield
    clear_registry()


@pytest.mark.unit
class TestCustomToolLoader:
    """Test suite for CustomToolLoader."""

    def test_discover_files_single_file_tools(self, tmp_path: Path) -> None:
        """Discover single .py files in tools directory."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool1.py").write_text(VALID_TOOL_CONTENT)
        (tools_dir / "tool2.py").write_text(ANOTHER_VALID_TOOL)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        files = loader.discover_files()

        # Assert
        assert len(files) == 2
        file_names = {f.name for f in files}
        assert "tool1.py" in file_names
        assert "tool2.py" in file_names

    def test_discover_files_package_style_tools(self, tmp_path: Path) -> None:
        """Discover package-style <name>/tool.py tools."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        pkg1_dir = tools_dir / "package1"
        pkg1_dir.mkdir()
        (pkg1_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        files = loader.discover_files()

        # Assert
        assert len(files) == 1
        assert files[0].name == "tool.py"
        assert files[0].parent.name == "package1"

    def test_discover_files_mixed_single_and_package(self, tmp_path: Path) -> None:
        """Discover both single-file and package-style tools."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "single.py").write_text(VALID_TOOL_CONTENT)
        pkg_dir = tools_dir / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "tool.py").write_text(ANOTHER_VALID_TOOL)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        files = loader.discover_files()

        # Assert
        assert len(files) == 2
        names = {f.name for f in files}
        assert "single.py" in names
        assert "tool.py" in names

    def test_discover_files_skips_dunder_files(self, tmp_path: Path) -> None:
        """Skip __init__.py and __pycache__ directories."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "__init__.py").write_text("")
        (tools_dir / "valid.py").write_text(VALID_TOOL_CONTENT)
        pycache = tools_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "something.pyc").write_text("")

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        files = loader.discover_files()

        # Assert
        assert len(files) == 1
        assert files[0].name == "valid.py"

    def test_discover_files_missing_directory(self, tmp_path: Path) -> None:
        """Return empty list when tools directory does not exist."""
        # Arrange
        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        files = loader.discover_files()

        # Assert
        assert files == []

    def test_load_all_single_valid_tool(self, tmp_path: Path) -> None:
        """Load a single valid tool successfully."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, diagnostics = loader.load_all()

        # Assert
        assert "test_custom_tool" in tools
        assert isinstance(tools["test_custom_tool"], ToolInfo)
        assert tools["test_custom_tool"].description == "A test custom tool"
        assert tools["test_custom_tool"].permission == "read"

        # Check diagnostics
        info_diags = [d for d in diagnostics if d.level == "info"]
        assert len(info_diags) == 1
        assert "test_custom_tool" in info_diags[0].message

    def test_load_all_multiple_valid_tools(self, tmp_path: Path) -> None:
        """Load multiple valid tools from different files."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool1.py").write_text(VALID_TOOL_CONTENT)
        (tools_dir / "tool2.py").write_text(ANOTHER_VALID_TOOL)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, diagnostics = loader.load_all()

        # Assert
        assert len(tools) == 2
        assert "test_custom_tool" in tools
        assert "another_tool" in tools

        info_diags = [d for d in diagnostics if d.level == "info"]
        assert len(info_diags) == 2

    def test_load_all_syntax_error_isolation(self, tmp_path: Path) -> None:
        """Syntax error in one file does not crash loader."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "valid.py").write_text(VALID_TOOL_CONTENT)
        (tools_dir / "broken.py").write_text(SYNTAX_ERROR_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, diagnostics = loader.load_all()

        # Assert
        assert len(tools) == 1
        assert "test_custom_tool" in tools

        error_diags = [d for d in diagnostics if d.level == "error"]
        assert len(error_diags) == 1
        assert "broken.py" in error_diags[0].file_path
        assert error_diags[0].code == "import_failed"

    def test_load_all_no_tools_found_warning(self, tmp_path: Path) -> None:
        """File with no tools produces warning diagnostic."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "no_tools.py").write_text(NO_TOOL_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, diagnostics = loader.load_all()

        # Assert
        assert len(tools) == 0

        warning_diags = [d for d in diagnostics if d.level == "warning"]
        assert len(warning_diags) == 1
        assert warning_diags[0].code == "no_tools_found"

    def test_load_all_duplicate_name_detection(self, tmp_path: Path) -> None:
        """Duplicate tool name produces warning, second skipped."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool1.py").write_text(VALID_TOOL_CONTENT)
        (tools_dir / "tool2.py").write_text(DUPLICATE_TOOL_NAME)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, diagnostics = loader.load_all()

        # Assert
        assert len(tools) == 1
        assert "test_custom_tool" in tools

        warning_diags = [
            d for d in diagnostics if d.level == "warning" and "duplicate" in d.message.lower()
        ]
        assert len(warning_diags) == 1
        assert "test_custom_tool" in warning_diags[0].message

    def test_load_all_registry_not_polluted(self, tmp_path: Path) -> None:
        """Custom tools do not remain in global _TOOL_REGISTRY."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, _ = loader.load_all()

        # Assert
        assert "test_custom_tool" in tools
        assert "test_custom_tool" not in _TOOL_REGISTRY

    def test_load_all_empty_directory(self, tmp_path: Path) -> None:
        """Empty tools directory returns empty results."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, diagnostics = loader.load_all()

        # Assert
        assert tools == {}
        assert diagnostics == []

    def test_load_custom_tools_convenience_function(self, tmp_path: Path) -> None:
        """load_custom_tools convenience function works correctly."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        # Act
        tools, diagnostics = load_custom_tools(base_path=tmp_path)

        # Assert
        assert "test_custom_tool" in tools
        assert isinstance(tools["test_custom_tool"], ToolInfo)
        assert len(diagnostics) > 0

    def test_load_custom_tools_custom_dirs(self, tmp_path: Path) -> None:
        """load_custom_tools with custom tools_dirs parameter."""
        # Arrange
        custom_dir = tmp_path / "custom_tools"
        custom_dir.mkdir(parents=True)
        (custom_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        # Act
        tools, diagnostics = load_custom_tools(
            base_path=tmp_path,
            tools_dirs=["custom_tools"],
        )

        # Assert
        assert "test_custom_tool" in tools
        info_diags = [d for d in diagnostics if d.level == "info"]
        assert len(info_diags) > 0

    def test_diagnostic_attributes(self, tmp_path: Path) -> None:
        """CustomToolDiagnostic contains all required attributes."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "broken.py").write_text(SYNTAX_ERROR_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        _, diagnostics = loader.load_all()

        # Assert
        assert len(diagnostics) > 0
        diag = diagnostics[0]
        assert isinstance(diag.file_path, str)
        assert isinstance(diag.code, str)
        assert isinstance(diag.message, str)
        assert diag.level in ("error", "warning", "info")

    def test_tool_info_is_executable(self, tmp_path: Path) -> None:
        """Loaded ToolInfo has valid execute callable."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, _ = loader.load_all()

        # Assert
        tool_info = tools["test_custom_tool"]
        assert callable(tool_info.execute)
        assert tool_info.name == "test_custom_tool"
        assert tool_info.parameters is not None
        assert tool_info.category == "custom"

    def test_discover_files_sorted_order(self, tmp_path: Path) -> None:
        """Discover files returns results in sorted order."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "zebra.py").write_text(VALID_TOOL_CONTENT)
        (tools_dir / "apple.py").write_text(ANOTHER_VALID_TOOL)
        (tools_dir / "middle.py").write_text(NO_TOOL_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        files = loader.discover_files()

        # Assert
        file_names = [f.name for f in files]
        assert file_names == sorted(file_names)
        assert file_names[0] == "apple.py"
        assert file_names[-1] == "zebra.py"

    def test_multiple_tools_dirs_parameter(self, tmp_path: Path) -> None:
        """CustomToolLoader with multiple tools_dirs."""
        # Arrange
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        (dir1 / "tool1.py").write_text(VALID_TOOL_CONTENT)

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        (dir2 / "tool2.py").write_text(ANOTHER_VALID_TOOL)

        loader = CustomToolLoader(
            base_path=tmp_path,
            tools_dirs=["dir1", "dir2"],
        )

        # Act
        files = loader.discover_files()

        # Assert
        assert len(files) == 2
        file_names = {f.name for f in files}
        assert "tool1.py" in file_names
        assert "tool2.py" in file_names


@pytest.mark.unit
class TestCustomToolLoaderWithHooks:
    """Test suite for CustomToolLoader definition hook integration."""

    def test_definition_hook_modifies_tool_info(self, tmp_path: Path) -> None:
        """Definition hook can modify tool metadata."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        registry = ToolHookRegistry()
        registry.register_definition(
            hook=lambda info: ToolInfo(
                name=info.name,
                description="modified description",
                parameters=info.parameters,
                execute=info.execute,
                permission=info.permission,
                category=info.category,
            ),
            pattern="test_custom_tool",
        )

        loader = CustomToolLoader(
            base_path=tmp_path,
            hook_registry=registry,
        )

        # Act
        tools, _diagnostics = loader.load_all()

        # Assert
        assert "test_custom_tool" in tools
        assert tools["test_custom_tool"].description == "modified description"

    def test_definition_hook_suppresses_tool(self, tmp_path: Path) -> None:
        """Definition hook returning None suppresses the tool."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        registry = ToolHookRegistry()
        registry.register_definition(
            hook=lambda _info: None,
            pattern="test_custom_tool",
        )

        loader = CustomToolLoader(
            base_path=tmp_path,
            hook_registry=registry,
        )

        # Act
        tools, diagnostics = loader.load_all()

        # Assert
        assert "test_custom_tool" not in tools
        suppressed = [d for d in diagnostics if d.code == "tool_suppressed_by_hook"]
        assert len(suppressed) == 1
        assert "test_custom_tool" in suppressed[0].message
        assert suppressed[0].level == "info"

    def test_definition_hook_no_match_passes_through(
        self,
        tmp_path: Path,
    ) -> None:
        """Hook with non-matching pattern does not affect the tool."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        registry = ToolHookRegistry()
        registry.register_definition(
            hook=lambda _info: None,  # Would suppress if matched
            pattern="nonexistent_*",
        )

        loader = CustomToolLoader(
            base_path=tmp_path,
            hook_registry=registry,
        )

        # Act
        tools, _diagnostics = loader.load_all()

        # Assert
        assert "test_custom_tool" in tools

    def test_no_hook_registry_passes_through(self, tmp_path: Path) -> None:
        """Without a hook registry, tools load normally."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        loader = CustomToolLoader(base_path=tmp_path)

        # Act
        tools, _diagnostics = loader.load_all()

        # Assert
        assert "test_custom_tool" in tools
        assert tools["test_custom_tool"].description == "A test custom tool"

    def test_load_custom_tools_with_hook_registry(
        self,
        tmp_path: Path,
    ) -> None:
        """Convenience function passes hook_registry through."""
        # Arrange
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "tool.py").write_text(VALID_TOOL_CONTENT)

        registry = ToolHookRegistry()
        registry.register_definition(
            hook=lambda _info: None,
            pattern="*",
        )

        # Act
        tools, diagnostics = load_custom_tools(
            base_path=tmp_path,
            hook_registry=registry,
        )

        # Assert
        assert len(tools) == 0
        suppressed = [d for d in diagnostics if d.code == "tool_suppressed_by_hook"]
        assert len(suppressed) == 1
