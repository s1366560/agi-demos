# Testing Guide

Patterns and techniques for testing custom tools.

## Test Setup

Every test file needs registry isolation. Without it, tools from one test leak into the next.

```python
import pytest
from pathlib import Path
from src.infrastructure.agent.tools.custom_tool_loader import CustomToolLoader
from src.infrastructure.agent.tools.define import ToolInfo, clear_registry

@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate the global tool registry per test."""
    clear_registry()
    yield
    clear_registry()
```

## Pattern 1: Test Tool Loading

Verify the tool is discovered and has correct metadata.

```python
TOOL_CODE = '''
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

@tool_define(
    name="word_count",
    description="Count words in text.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Input text"},
        },
        "required": ["text"],
    },
    permission="read",
    category="custom",
)
async def word_count(ctx, text: str) -> ToolResult:
    count = len(text.split())
    return ToolResult(output=f"{count} words")
'''

@pytest.mark.unit
class TestWordCountTool:
    def _write_tool(self, tmp_path: Path) -> CustomToolLoader:
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "word_count.py").write_text(TOOL_CODE)
        return CustomToolLoader(base_path=tmp_path)

    def test_loads_successfully(self, tmp_path: Path):
        loader = self._write_tool(tmp_path)
        tools, diagnostics = loader.load_all()

        assert "word_count" in tools
        assert isinstance(tools["word_count"], ToolInfo)
        assert tools["word_count"].permission == "read"
        assert tools["word_count"].category == "custom"
        assert not diagnostics

    def test_has_correct_parameters(self, tmp_path: Path):
        loader = self._write_tool(tmp_path)
        tools, _ = loader.load_all()

        params = tools["word_count"].parameters
        assert "text" in params["properties"]
        assert "text" in params["required"]
```

## Pattern 2: Test Tool Execution

Test the actual tool logic by calling the `execute` callable directly.

```python
import asyncio
from unittest.mock import MagicMock

@pytest.mark.unit
class TestWordCountExecution:
    def test_counts_words(self, tmp_path: Path):
        loader = self._write_tool(tmp_path)
        tools, _ = loader.load_all()

        ctx = MagicMock()  # Mock ToolContext
        result = asyncio.get_event_loop().run_until_complete(
            tools["word_count"].execute(ctx, text="hello world foo")
        )

        assert result.output == "3 words"
        assert not result.is_error

    def test_empty_string(self, tmp_path: Path):
        loader = self._write_tool(tmp_path)
        tools, _ = loader.load_all()

        ctx = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(
            tools["word_count"].execute(ctx, text="")
        )

        assert "0" in result.output or "1" in result.output
```

## Pattern 3: Test Error Cases

Verify the loader handles bad tools gracefully.

```python
@pytest.mark.unit
class TestToolLoadingErrors:
    def test_syntax_error_isolated(self, tmp_path: Path):
        """A broken file should not prevent other tools from loading."""
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)

        # Write a broken tool
        (tools_dir / "broken.py").write_text("def foo(:\n  pass")

        # Write a valid tool
        (tools_dir / "valid.py").write_text(TOOL_CODE)

        loader = CustomToolLoader(base_path=tmp_path)
        tools, diagnostics = loader.load_all()

        # Valid tool still loads
        assert "word_count" in tools

        # Broken tool produces a diagnostic
        assert len(diagnostics) >= 1
        assert any("broken.py" in d.source for d in diagnostics)

    def test_missing_decorator(self, tmp_path: Path):
        """A file without @tool_define produces no tools and no crash."""
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "empty.py").write_text("x = 42\n")

        loader = CustomToolLoader(base_path=tmp_path)
        tools, diagnostics = loader.load_all()

        assert len(tools) == 0  # No tools registered

    def test_duplicate_name_rejected(self, tmp_path: Path):
        """Two tools with the same name produce a diagnostic."""
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)

        tool_a = TOOL_CODE  # name="word_count"
        tool_b = TOOL_CODE.replace("word_count.py", "word_count_v2.py")

        (tools_dir / "tool_a.py").write_text(tool_a)
        (tools_dir / "tool_b.py").write_text(tool_a)  # Same name

        loader = CustomToolLoader(base_path=tmp_path)
        tools, diagnostics = loader.load_all()

        # One loaded, one rejected
        assert "word_count" in tools
        assert any("duplicate" in d.message.lower() for d in diagnostics)
```

## Pattern 4: Test Package-Style Tools

```python
@pytest.mark.unit
class TestPackageTool:
    def test_package_style_loads(self, tmp_path: Path):
        pkg_dir = tmp_path / ".memstack" / "tools" / "my_package"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "tool.py").write_text(TOOL_CODE)

        loader = CustomToolLoader(base_path=tmp_path)
        tools, diagnostics = loader.load_all()

        assert "word_count" in tools
        assert not diagnostics
```

## Pattern 5: Test with Definition Hooks

```python
from src.infrastructure.agent.tools.hooks import ToolHookRegistry

@pytest.mark.unit
class TestDefinitionHooks:
    def test_hook_modifies_metadata(self, tmp_path: Path):
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "word_count.py").write_text(TOOL_CODE)

        registry = ToolHookRegistry()
        registry.register_definition(
            name="add_prefix",
            hook=lambda info: ToolInfo(
                name=f"custom_{info.name}",
                description=info.description,
                parameters=info.parameters,
                execute=info.execute,
                permission=info.permission,
                category=info.category,
            ),
        )

        loader = CustomToolLoader(
            base_path=tmp_path,
            hook_registry=registry,
        )
        tools, _ = loader.load_all()

        assert "custom_word_count" in tools
        assert "word_count" not in tools

    def test_hook_suppresses_tool(self, tmp_path: Path):
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "word_count.py").write_text(TOOL_CODE)

        registry = ToolHookRegistry()
        registry.register_definition(
            name="block_all",
            hook=lambda info: None,  # Suppress
        )

        loader = CustomToolLoader(
            base_path=tmp_path,
            hook_registry=registry,
        )
        tools, diagnostics = loader.load_all()

        assert "word_count" not in tools
        assert any("suppressed" in d.message.lower() for d in diagnostics)
```

## Running Tests

```bash
# Run all custom tool tests
uv run pytest src/tests/unit/test_custom_tool_loader.py -v

# Run a specific test class
uv run pytest src/tests/unit/test_custom_tool_loader.py::TestMyTool -v

# Run with coverage
uv run pytest src/tests/unit/test_custom_tool_loader.py --cov=src.infrastructure.agent.tools.custom_tool_loader -v
```

## Tips

- Always use `autouse` fixture for `clear_registry()` -- forgetting this causes flaky tests.
- Use `tmp_path` (pytest built-in) for filesystem isolation -- never write to the real `.memstack/tools/`.
- Mock `ToolContext` with `MagicMock()` for execution tests -- tools only need `ctx` attributes they actually access.
- Test both success and error paths -- `CustomToolLoader` returns diagnostics, not exceptions.
