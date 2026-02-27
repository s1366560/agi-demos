# API Reference

Detailed API documentation for the custom tool system.

## ToolContext

**Import**: `from src.infrastructure.agent.tools.context import ToolContext`

Every tool receives a `ToolContext` as its first argument. It provides identity, cancellation, and event emission.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Current session identifier |
| `message_id` | `str` | Identifier of the triggering message |
| `call_id` | `str` | Unique identifier for this tool invocation |
| `agent_name` | `str` | Name of the agent executing the tool |
| `conversation_id` | `str` | Conversation scope for this execution |
| `abort_signal` | `asyncio.Event` | Cancellation signal; set to request abort |
| `messages` | `list[Any]` | Read-only snapshot of conversation messages |

### Methods

#### `await ctx.metadata(data: dict)`
Emit metadata update to the UI in real-time.

```python
await ctx.metadata({"progress": 50, "stage": "processing"})
```

#### `await ctx.emit(event: Any)`
Emit a domain event (task update, artifact, etc.). Events are collected by the pipeline automatically.

```python
from src.infrastructure.agent.tools.result import ToolEvent
await ctx.emit(ToolEvent(type="custom", tool_name="my_tool", data={"key": "value"}))
```

#### `await ctx.ask(permission: str, description: str = "") -> bool`
Request user permission. Blocks until the user responds.

```python
if await ctx.ask("write", "Delete temporary files?"):
    do_delete()
else:
    return ToolResult(output="Operation cancelled by user")
```

#### `await ctx.race(awaitable, timeout=None) -> Any`
Race an awaitable against the abort signal and optional timeout. Use for long-running operations.

```python
try:
    result = await ctx.race(fetch_data(url), timeout=30.0)
except ToolAbortedError:
    return ToolResult(output="Aborted", is_error=True)
except TimeoutError:
    return ToolResult(output="Timed out", is_error=True)
```

---

## ToolResult

**Import**: `from src.infrastructure.agent.tools.result import ToolResult`

Structured return value from tool execution. The `output` field is what the LLM sees.

### Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `output` | `str` | (required) | Main output content for LLM consumption |
| `title` | `str \| None` | `None` | Short title for UI display |
| `metadata` | `dict[str, Any]` | `{}` | Structured metadata dict |
| `attachments` | `list[ToolAttachment]` | `[]` | File attachments produced by the tool |
| `is_error` | `bool` | `False` | Whether this result represents an error |
| `was_truncated` | `bool` | `False` | Whether output was truncated |
| `original_bytes` | `int \| None` | `None` | Original size before truncation |
| `full_output_path` | `str \| None` | `None` | Path to full output if truncated |

### Usage Patterns

```python
# Success
return ToolResult(output="Done: created 3 files")

# Error
return ToolResult(output="File not found: /path", is_error=True)

# With metadata
return ToolResult(
    output="Query returned 42 rows",
    title="SQL Query",
    metadata={"row_count": 42, "duration_ms": 150},
)
```

---

## ToolAttachment

**Import**: `from src.infrastructure.agent.tools.result import ToolAttachment`

File attachment from tool execution.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | (required) | Filename or identifier |
| `content` | `bytes \| str` | (required) | Raw bytes or text content |
| `mime_type` | `str` | `"application/octet-stream"` | MIME type |

```python
return ToolResult(
    output="Generated report",
    attachments=[
        ToolAttachment(name="report.csv", content=csv_text, mime_type="text/csv"),
    ],
)
```

---

## ToolInfo

**Import**: `from src.infrastructure.agent.tools.define import ToolInfo`

Metadata container returned by `@tool_define`. This is what the decorator produces instead of the original function.

### Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | (required) | Unique tool name for LLM function calling |
| `description` | `str` | (required) | Human-readable description for the LLM |
| `parameters` | `dict[str, Any]` | (required) | JSON Schema dict for parameters |
| `execute` | `Callable[..., Awaitable[Any]]` | (required) | The actual async callable |
| `permission` | `str \| None` | `None` | Permission identifier |
| `category` | `str` | `"general"` | Tool category for grouping |
| `model_filter` | `Callable[[str], bool] \| None` | `None` | Optional model availability predicate |
| `tags` | `frozenset[str]` | `frozenset()` | Freeform tags for filtering |

---

## @tool_define Decorator

**Import**: `from src.infrastructure.agent.tools.define import tool_define`

Decorator factory that converts an async function into a `ToolInfo` and registers it in the global registry.

### Signature

```python
@tool_define(
    name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    permission: str | None = None,
    category: str = "general",
    model_filter: Callable[[str], bool] | None = None,
    tags: frozenset[str] | None = None,
)
```

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `name` | Yes | Unique tool name (used in LLM tool calls) |
| `description` | Yes | Human-readable description shown to the LLM |
| `parameters` | Yes | JSON Schema dict for the tool's input parameters |
| `permission` | No | Permission identifier: `"read"`, `"write"`, `"admin"` |
| `category` | No | Grouping category (default: `"general"`, use `"custom"` for custom tools) |
| `model_filter` | No | Predicate `(model_id) -> bool` to restrict tool to certain models |
| `tags` | No | Freeform tags for filtering |

---

## CustomToolLoader

**Import**: `from src.infrastructure.agent.tools.custom_tool_loader import CustomToolLoader`

Discovers and loads custom tools from the filesystem.

### Constructor

```python
CustomToolLoader(
    base_path: Path = Path("."),
    tools_dirs: Sequence[str] = (".memstack/tools",),
    hook_registry: ToolHookRegistry | None = None,
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_path` | `Path(".")` | Project root directory |
| `tools_dirs` | `(".memstack/tools",)` | Directories to scan (relative to base_path) |
| `hook_registry` | `None` | Optional hook registry for definition hooks |

### Methods

#### `load_all() -> tuple[dict[str, ToolInfo], list[CustomToolDiagnostic]]`

Scan all tool directories and load tools. Returns a tuple of:
- `dict[str, ToolInfo]`: Successfully loaded tools keyed by name
- `list[CustomToolDiagnostic]`: Diagnostics for any issues encountered

```python
loader = CustomToolLoader(base_path=Path("/project"))
tools, diagnostics = loader.load_all()

for name, tool_info in tools.items():
    print(f"Loaded: {name} ({tool_info.description})")

for diag in diagnostics:
    print(f"Issue: {diag.source} - {diag.message}")
```

### CustomToolDiagnostic

| Attribute | Type | Description |
|-----------|------|-------------|
| `source` | `str` | File path that caused the issue |
| `message` | `str` | Human-readable error description |
| `error` | `Exception \| None` | Original exception if applicable |

---

## Registry Utilities

### `get_registered_tools() -> dict[str, ToolInfo]`
Return all tools currently in the global registry.

### `clear_registry() -> None`
Clear the global registry. Use in tests with an `autouse` fixture to ensure isolation.

```python
@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()
```
