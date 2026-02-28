---
name: custom-tool-development
description: Guide for developing, testing, and debugging custom tools that extend the agent's capabilities. Use when users want to create a new custom tool, add a tool to .memstack/tools/, write a tool using @tool_define, test a custom tool with CustomToolLoader, debug tool loading errors, or understand the custom tool API (ToolInfo, ToolContext, ToolResult).
license: Apache-2.0
compatibility: Requires Python 3.12+, project with .memstack/tools/ directory
metadata:
  author: memstack-team
  version: "1.0"
---

# Custom Tool Development

Create custom tools by dropping Python files into `.memstack/tools/`. The agent discovers them automatically at startup via `CustomToolLoader`.

## File Structure

```
.memstack/tools/
├── my_tool.py              # Single-file tool
├── example_tool.py         # Built-in example (reference)
└── my_package/
    └── tool.py             # Package-style tool
```

Both patterns are equivalent. Use package-style when the tool needs helper modules.

## Creating a Tool

### Minimal Template

```python
from memstack_tools import tool_define, ToolResult
@tool_define(
    name="my_tool",
    description="One-line description shown to the LLM.",
    parameters={
        "type": "object",
        "properties": {
            "arg1": {"type": "string", "description": "First argument"},
        },
        "required": ["arg1"],
    },
    permission="read",
    category="custom",
)
async def my_tool(ctx, arg1: str) -> ToolResult:
    return ToolResult(output=f"Result: {arg1}")
```

### Key Rules

1. **Decorator required**: Every tool function must use `@tool_define`. Without it, the tool is not discovered.
2. **Async required**: Tool functions must be `async def`.
3. **First param is `ctx`**: A `ToolContext` instance (access `ctx.conversation_id`, `ctx.session_id`, `ctx.agent_name`).
4. **Return `ToolResult`**: Use `output` for the LLM-visible string, `is_error=True` for errors.
5. **Unique name**: No two tools can share the same `name`. Duplicates are rejected with a diagnostic.
6. **Import errors are isolated**: A broken tool file does not break other tools.

### Permission Levels

| Value | Meaning |
|-------|---------|
| `"read"` | Safe, no user approval needed (default for custom tools) |
| `"write"` | Modifies state, may require approval |
| `"admin"` | Dangerous operations, always requires approval |

### Parameters Schema

Use JSON Schema format. Supported types: `string`, `number`, `integer`, `boolean`, `array`, `object`.

```python
parameters={
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query"},
        "limit": {"type": "integer", "description": "Max results", "default": 10},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Filter tags",
        },
    },
    "required": ["query"],
}
```

### Error Handling

Return errors via `ToolResult`, never raise exceptions:

```python
@tool_define(name="safe_tool", ...)
async def safe_tool(ctx, path: str) -> ToolResult:
    try:
        result = do_work(path)
        return ToolResult(output=result)
    except FileNotFoundError:
        return ToolResult(output=f"File not found: {path}", is_error=True)
    except Exception as e:
        return ToolResult(output=f"Unexpected error: {e}", is_error=True)
```

## Testing a Tool

Use `CustomToolLoader` with `tmp_path` to test in isolation. See [references/testing-guide.md](references/testing-guide.md) for detailed patterns.

### Quick Test Pattern

```python
import pytest
from pathlib import Path
from src.infrastructure.agent.tools.custom_tool_loader import CustomToolLoader
from src.infrastructure.agent.tools.define import ToolInfo, clear_registry

TOOL_CODE = '''
from memstack_tools import tool_define, ToolResult

@tool_define(
    name="test_tool",
    description="Test tool",
    parameters={"type": "object", "properties": {}, "required": []},
    permission="read",
    category="custom",
)
async def test_tool(ctx) -> ToolResult:
    return ToolResult(output="ok")
'''

@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()

@pytest.mark.unit
class TestMyTool:
    def test_loads_successfully(self, tmp_path: Path):
        tools_dir = tmp_path / ".memstack" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "test_tool.py").write_text(TOOL_CODE)

        loader = CustomToolLoader(base_path=tmp_path)
        tools, diagnostics = loader.load_all()

        assert "test_tool" in tools
        assert isinstance(tools["test_tool"], ToolInfo)
        assert not diagnostics  # No errors
```

Run tests: `uv run pytest src/tests/unit/test_my_tool.py -v`

## Debugging Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Tool not discovered | Missing `@tool_define` decorator | Add decorator to function |
| Tool not discovered | File not in `.memstack/tools/` | Move file to correct directory |
| Tool not discovered | Package missing `tool.py` | Rename entry file to `tool.py` |
| `ImportError` in diagnostic | Bad import path | Check `from memstack_tools import ...` imports |
| Duplicate tool diagnostic | Two tools share same `name` | Rename one tool's `name` parameter |
| `TypeError` at runtime | Missing `ctx` first parameter | Add `ctx` as first positional arg |
| Tool returns nothing to LLM | Forgot `ToolResult` | Return `ToolResult(output=...)` |

## API Reference

For complete API documentation of `ToolContext`, `ToolResult`, `ToolInfo`, and `CustomToolLoader`, see [references/api-reference.md](references/api-reference.md).

### Quick Reference

- **`ToolContext`** -- `ctx.session_id`, `ctx.conversation_id`, `ctx.agent_name`, `ctx.emit(event)`, `ctx.ask(permission)`
- **`ToolResult`** -- `ToolResult(output=str, is_error=bool, title=str, metadata=dict, attachments=list)`
- **`ToolInfo`** -- Returned by `@tool_define`. Fields: `name`, `description`, `parameters`, `execute`, `permission`, `category`, `tags`
- **`CustomToolLoader`** -- `loader = CustomToolLoader(base_path=Path(".")); tools, diagnostics = loader.load_all()`

## Working Example

See `.memstack/tools/example_tool.py` for a complete, working custom tool with inline documentation.

## Sandbox Development Environment

When developing custom tools inside a sandbox container, the following directory layout is available:

```
Container paths:
  /workspace/                    # Main workspace (read-write)
  /workspace/.memstack/          # .memstack overlay (read-write, synced to host)
  /workspace/.memstack/tools/    # Write your custom tools here
  /host_src/                     # Host project source code (read-only reference)
```

### Key Points for Sandbox Development

1. **Write tools to `/workspace/.memstack/tools/`** -- Files written here are immediately synced to the host's `.memstack/tools/` directory via a direct bind mount.
2. **Read host source from `/host_src/`** -- The host project's `src/` directory is mounted read-only at `/host_src/`. Use this to reference existing code patterns, imports, and APIs.
3. **Import paths in tools** -- Custom tools use `from memstack_tools import tool_define, ToolResult`. The `memstack_tools` package is a thin public SDK that re-exports the internal types. These imports resolve against the host Python environment at agent startup, not inside the sandbox.
4. **Test inside sandbox** -- You can create test files and run `pytest` within `/workspace/`. Copy necessary test fixtures from `/host_src/` if needed.
5. **The `/host_src/` path is read-only** -- You cannot modify host source code from the sandbox. This is intentional for safety.

### Sandbox Workflow

```
1. Read reference code:    read /host_src/infrastructure/agent/tools/define.py
2. Create tool file:       write /workspace/.memstack/tools/my_tool.py
3. Test tool (optional):   bash pytest /workspace/test_my_tool.py -v
4. Tool appears on host:   Automatically via bind mount
5. Agent restart picks up:  CustomToolLoader discovers the new tool
```
