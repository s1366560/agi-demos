# Architecture Design: Plugin Tool Pipeline Fix

**Date**: 2026-03-01
**Status**: Proposed
**Scope**: Agent plugin tool loading, execution, and dependency management
**Conversation**: `8f8a299c-0d0b-4525-815c-c0ed540858b4`

---

## 1. Problem Statement

The MemStack agent cannot use custom plugin tools (specifically the `pdf-assistant` plugin). Three classes of failure were observed:

1. **ToolResult API mismatch** -- custom tool code uses `ToolResult(error=...)` but the actual class has no `error` parameter.
2. **Plugin tools fail silently** -- plugin tool factories return raw Python objects (e.g. `PDFCreateTool()`) that the tool converter cannot execute.
3. **Missing dependencies** -- plugin tools import libraries (`reportlab`, `pypdf`, `pdfplumber`) that are not installed in the host environment, with no dependency management for non-sandbox plugin tools.

The agent worked around the failures by using the `bash` tool to run Python directly, which succeeded but bypasses the entire plugin tool system.

---

## 2. Root Cause Analysis

### RC-1: `ToolResult` Has No `error` Parameter

**File**: `src/infrastructure/agent/tools/result.py`

The `ToolResult` dataclass signature:

```python
@dataclass
class ToolResult:
    output: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[ToolAttachment] = field(default_factory=list)
    is_error: bool = False           # <- The actual error flag
    was_truncated: bool = False
    original_bytes: int | None = None
    full_output_path: str | None = None
```

The `.memstack/tools/pdf_tools.py` custom tool code uses:
```python
ToolResult(output="", error=f"Error: {e}")  # WRONG -- 'error' is not a valid parameter
```

The correct usage is `ToolResult(output=f"Error: {e}", is_error=True)`.

**Impact**: Any custom tool using `error=` fails at import/call time with `TypeError: ToolResult.__init__() got an unexpected keyword argument 'error'`.

---

### RC-2: Plugin Tool Factory Returns Raw Objects, Not `ToolInfo`

**Files**:
- `.memstack/plugins/pdf-assistant/plugin.py` (line 109-125)
- `src/infrastructure/agent/plugins/registry.py` (line 641-695)
- `src/infrastructure/agent/state/agent_worker_state.py` (line 862-892)
- `src/infrastructure/agent/core/tool_converter.py` (line 134-194)

**The pipeline**:

```
PDFAssistantPlugin.setup(api):
  api.register_tool_factory(_tool_factory)

_tool_factory(_context) returns:
  {"pdf_create": PDFCreateTool(), "pdf_extract_text": PDFExtractTextTool(), ...}

build_tools(context):
  # Iterates factories, returns raw tool objects
  plugin_tools["pdf_create"] = PDFCreateTool()  # Raw object, NOT ToolInfo

_add_plugin_tools():
  tools.update(plugin_tools)  # Raw PDFTool instances go into tools dict

convert_tools(tools):
  for name, tool in tools.items():
    if isinstance(tool, ToolInfo):   # NO -- PDFCreateTool is not ToolInfo
      ...
    else:  # Falls to legacy path
      # _resolve_execute_method looks for: execute, ainvoke, _arun, _run, run
      # PDFCreateTool has NONE of these -- it only has __call__
      # Result: _resolve_execute_method returns None
      # The wrapper returns "Error executing tool pdf_create: Tool pdf_create has no execute method"
```

**The specific gap**: `_resolve_execute_method` checks for `execute`, `ainvoke`, `_arun`, `_run`, `run` -- but NOT `__call__`. Plugin tools that use `__call__` as their execution method are silently broken.

Additionally, the legacy path extracts:
- `description` via `getattr(tool, "description", f"Tool: {name}")` -- This works (PDFTool has `description` class attribute)
- `parameters` via `_get_tool_parameters` -- This returns empty `{}` because PDFTool has no `get_parameters_schema()` or `args_schema`

So even if `__call__` were resolved, the LLM would see tools with **empty parameter schemas** and could not call them correctly.

---

### RC-3: Plugin Tools Return `dict`, Not `ToolResult` or `str`

**File**: `.memstack/plugins/pdf-assistant/tools.py`

All `PDFTool.__call__` methods return `dict[str, Any]`:
```python
def __call__(self, input_file: str, ...) -> dict[str, Any]:
    return {"status": "success", "tool": self.name, "pages": count}
```

The agent's tool execution pipeline expects:
- **New tools** (`ToolInfo`): Return `ToolResult`
- **Legacy tools** (`AgentToolBase`): Return `str`

A `dict` return value would be passed through as-is, which may or may not serialize correctly depending on the downstream processing. This is a contract mismatch.

---

### RC-4: No Dependency Management for Non-Sandbox Plugin Tools

**Files**:
- `src/infrastructure/agent/state/agent_worker_state.py` (line 862-892 vs 895-954)

Two parallel tool loading paths exist:

| Path | Registration | Dependency Mgmt | Used By |
|------|-------------|-----------------|---------|
| `_add_plugin_tools()` | `api.register_tool_factory()` | **None** | pdf-assistant |
| `_add_sandbox_plugin_tools()` | `api.register_sandbox_tool_factory()` | `DependencyOrchestrator` | (none currently) |

The pdf-assistant plugin uses `register_tool_factory()` (non-sandbox path), so it gets **zero** dependency management. When the tool tries to `from pypdf import PdfReader`, it fails if `pypdf` is not installed in the host environment.

The sandbox path has full dependency management (`DependencyOrchestrator` -> `SandboxDependencyInstaller` -> installs deps in sandbox before first tool call), but the pdf-assistant plugin does not use it.

---

### RC-5: Sandbox vs Non-Sandbox Factory Split Creates Confusion

The plugin API exposes two registration methods:
- `api.register_tool_factory(fn)` -- non-sandbox, no dependency management
- `api.register_sandbox_tool_factory(fn)` -- sandbox, with dependency management

The sandbox path (`_build_tool_from_meta`) expects factories to return `dict` values that are **metadata dicts** (`{"description": ..., "parameters": ..., "dependencies": ...}`), NOT raw tool instances.

The non-sandbox path (`build_tools`) expects factories to return **tool instances** (objects with execute methods).

Plugin authors have no clear documentation on which to use, what format to return, or how dependencies are handled.

---

## 3. Proposed Solutions

### Fix 1: Add Backward-Compatible `error` Parameter to `ToolResult`

**Approach**: Accept `error` as an alias for setting `output` + `is_error=True`.

**File**: `src/infrastructure/agent/tools/result.py`

```python
@dataclass
class ToolResult:
    output: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[ToolAttachment] = field(default_factory=list)
    is_error: bool = False
    was_truncated: bool = False
    original_bytes: int | None = None
    full_output_path: str | None = None

    def __post_init__(self) -> None:
        # Note: __post_init__ cannot handle unknown kwargs in a dataclass.
        # Instead, use a factory classmethod or update the SDK docs.
        pass

    @classmethod
    def error(cls, message: str, **kwargs: Any) -> ToolResult:
        """Create an error ToolResult.

        Convenience factory for plugins that previously used
        ``ToolResult(error=message)``.
        """
        return cls(output=message, is_error=True, **kwargs)

    @classmethod
    def success(cls, output: str, **kwargs: Any) -> ToolResult:
        """Create a success ToolResult."""
        return cls(output=output, is_error=False, **kwargs)
```

**Additionally**: Fix `.memstack/tools/pdf_tools.py` to use the correct API:
```python
# Before
ToolResult(output="", error=f"Error: {e}")
# After
ToolResult(output=f"Error: {e}", is_error=True)
# Or with the new factory:
ToolResult.error(f"Error: {e}")
```

**Additionally**: Update `memstack_tools/__init__.py` SDK to re-export the factory methods and add documentation.

**Backward compatibility**: Fully backward compatible. Existing code using `ToolResult(output=..., is_error=True)` continues to work. New `ToolResult.error()` is additive.

---

### Fix 2: Plugin Tool Adapter Layer in `_add_plugin_tools`

**Approach**: After `build_tools()` returns raw tool objects, wrap each one as a proper `ToolInfo` before adding to the tools dict. This is the **core fix**.

**File**: `src/infrastructure/agent/state/agent_worker_state.py` -- new function `_adapt_plugin_tool`

```python
def _adapt_plugin_tool(
    tool_name: str,
    tool_impl: Any,
    plugin_name: str,
) -> ToolInfo | None:
    """Adapt a raw plugin tool object into a ToolInfo.

    Plugin tool factories return arbitrary objects. This function inspects
    the object and wraps it as a ToolInfo that the agent pipeline can
    consume.

    Supports:
    - Objects with ``__call__`` (e.g. PDFTool subclasses)
    - Objects with ``execute`` / ``run`` methods
    - ToolInfo instances (returned as-is)
    - dict metadata (description + parameters + execute)
    """
    from src.infrastructure.agent.tools.define import ToolInfo
    from src.infrastructure.agent.tools.result import ToolResult

    # Already a ToolInfo -- pass through
    if isinstance(tool_impl, ToolInfo):
        return tool_impl

    # Extract description
    description = getattr(tool_impl, "description", "") or f"Plugin tool: {tool_name}"

    # Extract parameters schema
    parameters: dict[str, Any] = {}
    if hasattr(tool_impl, "get_parameters_schema"):
        parameters = tool_impl.get_parameters_schema()
    elif hasattr(tool_impl, "parameters"):
        parameters = tool_impl.parameters
    # If still empty, attempt to introspect __call__ signature
    if not parameters:
        parameters = _introspect_callable_parameters(tool_impl, tool_name)

    # Find the callable
    callable_fn = None
    for attr_name in ("execute", "ainvoke", "_arun", "_run", "run", "__call__"):
        fn = getattr(tool_impl, attr_name, None)
        if fn is not None and callable(fn):
            callable_fn = fn
            break

    if callable_fn is None:
        logger.warning(
            "Plugin tool '%s' from '%s' has no callable method, skipping",
            tool_name,
            plugin_name,
        )
        return None

    # Build the async execute wrapper
    async def execute(ctx: Any, **kwargs: Any) -> ToolResult:
        """Adapted plugin tool execution."""
        import asyncio
        import inspect as _inspect

        _ = ctx  # Plugin tools don't use ToolContext

        try:
            result = callable_fn(**kwargs)
            if _inspect.isawaitable(result):
                result = await result

            # Normalize return value to ToolResult
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, dict):
                # Convention: {"status": "error", ...} or {"status": "success", ...}
                status = result.get("status", "success")
                if status == "error":
                    error_msg = result.get("error", str(result))
                    return ToolResult(output=str(error_msg), is_error=True)
                return ToolResult(output=str(result))
            return ToolResult(output=str(result))
        except Exception as e:
            return ToolResult(output=f"Plugin tool error: {e}", is_error=True)

    return ToolInfo(
        name=tool_name,
        description=description,
        parameters=parameters,
        execute=execute,
        permission=getattr(tool_impl, "permission", None),
        category="plugin",
        tags=frozenset({"plugin", plugin_name}),
    )
```

**New helper** -- `_introspect_callable_parameters`:

```python
def _introspect_callable_parameters(
    tool_impl: Any,
    tool_name: str,
) -> dict[str, Any]:
    """Introspect a callable's signature to generate a JSON Schema parameters dict.

    This enables plugin tools that don't declare explicit schemas to still
    work with the LLM function calling interface.
    """
    import inspect as _inspect

    callable_fn = None
    for attr_name in ("execute", "__call__", "run"):
        fn = getattr(tool_impl, attr_name, None)
        if fn is not None and callable(fn):
            callable_fn = fn
            break

    if callable_fn is None:
        return {"type": "object", "properties": {}, "required": []}

    sig = _inspect.signature(callable_fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "ctx", "context", "kwargs"):
            continue

        prop: dict[str, Any] = {}

        # Infer type from annotation
        annotation = param.annotation
        if annotation is not _inspect.Parameter.empty:
            type_map = {
                str: "string",
                int: "integer",
                float: "number",
                bool: "boolean",
                list: "array",
                dict: "object",
            }
            origin = getattr(annotation, "__origin__", annotation)
            prop["type"] = type_map.get(origin, "string")
        else:
            prop["type"] = "string"

        # Handle default values
        if param.default is _inspect.Parameter.empty:
            required.append(param_name)
        else:
            if param.default is not None:
                prop["default"] = param.default

        properties[param_name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
```

**Update `_add_plugin_tools`**:

```python
async def _add_plugin_tools(
    tools: dict[str, Any],
    tenant_id: str,
    project_id: str,
) -> None:
    """Load plugin runtime and add plugin-provided tools."""
    runtime_manager = get_plugin_runtime_manager()
    runtime_diagnostics = await runtime_manager.ensure_loaded()
    for diagnostic in runtime_diagnostics:
        _log_plugin_diagnostic(diagnostic, context="runtime_load")

    plugin_registry = get_plugin_registry()
    plugin_tools, diagnostics = await plugin_registry.build_tools(
        PluginToolBuildContext(
            tenant_id=tenant_id,
            project_id=project_id,
            base_tools=tools,
        )
    )
    for diagnostic in diagnostics:
        _log_plugin_diagnostic(diagnostic, context="tool_build")

    if plugin_tools:
        adapted_count = 0
        for tool_name, tool_impl in plugin_tools.items():
            # NEW: Adapt raw plugin tools to ToolInfo
            adapted = _adapt_plugin_tool(
                tool_name=tool_name,
                tool_impl=tool_impl,
                plugin_name="unknown",  # plugin_name not available here; see Fix 2b
            )
            if adapted is not None:
                tools[tool_name] = adapted
                adapted_count += 1
            else:
                logger.warning(
                    "Agent Worker: Skipped unadaptable plugin tool '%s'",
                    tool_name,
                )

        logger.info(
            "Agent Worker: Added %d plugin tools for project %s (adapted %d)",
            len(plugin_tools),
            project_id,
            adapted_count,
        )
```

**Fix 2b**: To pass `plugin_name` through, modify `build_tools()` to return tuples of `(plugin_name, tool_name, tool_impl)` or annotate tool objects with `_plugin_name`. The simplest approach: tag each tool with the plugin name in `build_tools()`:

```python
# In registry.py build_tools(), after line 675:
plugin_tools[tool_name] = tool_impl
# Add:
if not isinstance(tool_impl, ToolInfo):
    try:
        tool_impl._plugin_origin = plugin_name  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        pass
```

Then in `_add_plugin_tools`, read `getattr(tool_impl, "_plugin_origin", "unknown")`.

---

### Fix 3: Dependency Declaration in Plugin Manifest

**Approach**: Extend `memstack.plugin.json` to declare Python/system dependencies. The `_add_plugin_tools` path checks the manifest and either pre-installs or warns.

**File**: `.memstack/plugins/pdf-assistant/memstack.plugin.json`

Add a `dependencies` section:

```json
{
  "id": "pdf-assistant",
  "kind": "tool",
  "name": "PDF Assistant",
  "version": "1.0.0",
  "dependencies": {
    "python": [
      "pypdf>=4.0",
      "pdfplumber>=0.10",
      "reportlab>=4.0",
      "openpyxl>=3.1",
      "Pillow>=10.0"
    ],
    "system": [
      "tesseract-ocr"
    ]
  }
}
```

**File**: `src/infrastructure/agent/plugins/manifest.py`

Extend `PluginManifestMetadata` to include dependencies:

```python
@dataclass
class PluginDependencies:
    python: list[str] = field(default_factory=list)
    system: list[str] = field(default_factory=list)
    node: list[str] = field(default_factory=list)

@dataclass
class PluginManifestMetadata:
    # ... existing fields ...
    dependencies: PluginDependencies | None = None
```

**File**: `src/infrastructure/agent/state/agent_worker_state.py`

In `_add_plugin_tools`, after loading the plugin tools, check manifest dependencies and install if needed:

```python
async def _ensure_plugin_dependencies(
    plugin_name: str,
    manifest: PluginManifestMetadata | None,
) -> bool:
    """Install Python dependencies declared in the plugin manifest.

    Returns True if all dependencies are satisfied, False otherwise.
    """
    if manifest is None or manifest.dependencies is None:
        return True

    python_deps = manifest.dependencies.python
    if not python_deps:
        return True

    missing = []
    for dep in python_deps:
        package_name = dep.split(">=")[0].split("==")[0].split("<")[0].strip()
        try:
            importlib.import_module(package_name.replace("-", "_"))
        except ImportError:
            missing.append(dep)

    if not missing:
        return True

    logger.info(
        "Plugin '%s' has missing dependencies: %s. Attempting install...",
        plugin_name,
        missing,
    )

    try:
        import subprocess
        result = subprocess.run(
            ["uv", "pip", "install", "--quiet"] + missing,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(
                "Failed to install dependencies for plugin '%s': %s",
                plugin_name,
                result.stderr,
            )
            return False
        return True
    except Exception as e:
        logger.error(
            "Dependency installation error for plugin '%s': %s",
            plugin_name,
            e,
        )
        return False
```

**Security note**: Only PyPI-style requirement specifiers are allowed (consistent with existing `plugin_manager` security policy). The function should validate specifiers before passing to `subprocess`.

---

### Fix 4: Fix the pdf-assistant Plugin Code

**File**: `.memstack/tools/pdf_tools.py`

Replace all `ToolResult(output="", error=...)` with `ToolResult(output=..., is_error=True)`.

**File**: `.memstack/plugins/pdf-assistant/tools.py`

The plugin tools currently return `dict`. With Fix 2 (adapter layer), this is handled automatically -- the adapter converts `dict` returns to `ToolResult`. No changes needed to the plugin code, but the plugin documentation should recommend returning `ToolResult` for new plugins.

---

### Fix 5: Unify or Document the Two Factory Paths

**Option A (Recommended)**: Enhance `_add_plugin_tools` to optionally use `DependencyOrchestrator` when a sandbox is available AND the plugin manifest declares dependencies. This means plugins registered via `register_tool_factory()` get automatic sandbox dependency management.

**Option B**: Document clearly that:
- `register_tool_factory()` = host-side tools, no dependency management, tool must be a callable object
- `register_sandbox_tool_factory()` = sandbox-side tools, full dependency management, factory must return metadata dicts

For Option A, the change to `_add_plugin_tools` would be:

```python
async def _add_plugin_tools(
    tools: dict[str, Any],
    tenant_id: str,
    project_id: str,
    sandbox_id: str | None = None,       # NEW
    sandbox_port: Any = None,             # NEW
    redis_client: Any = None,             # NEW
) -> None:
    """Load plugin runtime and add plugin-provided tools.

    When sandbox_id/sandbox_port are provided AND a plugin declares
    dependencies, tools are wrapped with sandbox dependency management
    instead of running on the host.
    """
    # ... existing ensure_loaded + build_tools ...

    # For each tool, decide: host execution or sandbox delegation
    for tool_name, tool_impl in plugin_tools.items():
        manifest = _get_plugin_manifest(tool_impl)
        has_deps = manifest and manifest.dependencies and manifest.dependencies.python

        if has_deps and sandbox_id and sandbox_port:
            # Route through sandbox with dependency management
            # (similar to _add_sandbox_plugin_tools path)
            ...
        else:
            # Host execution with adapter
            adapted = _adapt_plugin_tool(tool_name, tool_impl, plugin_name)
            if adapted:
                tools[tool_name] = adapted
```

---

## 4. Implementation Plan

### Phase 1: Critical Fixes (Immediate)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 1.1 | Add `ToolResult.error()` and `ToolResult.success()` factory methods | `result.py`, `memstack_tools/__init__.py` | S |
| 1.2 | Fix `.memstack/tools/pdf_tools.py` to use correct `ToolResult` API | `.memstack/tools/pdf_tools.py` | S |
| 1.3 | Add `__call__` to `_resolve_execute_method` in `tool_converter.py` | `tool_converter.py` | S |
| 1.4 | Implement `_adapt_plugin_tool` function | `agent_worker_state.py` | M |
| 1.5 | Implement `_introspect_callable_parameters` function | `agent_worker_state.py` (or new `plugin_tool_adapter.py`) | M |
| 1.6 | Update `_add_plugin_tools` to use adapter | `agent_worker_state.py` | S |

**Estimated effort**: 1-2 days

### Phase 2: Dependency Management (Short-term)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 2.1 | Extend `PluginManifestMetadata` with `PluginDependencies` | `manifest.py` | S |
| 2.2 | Update `memstack.plugin.json` for pdf-assistant with deps | `.memstack/plugins/pdf-assistant/memstack.plugin.json` | S |
| 2.3 | Implement `_ensure_plugin_dependencies` | `agent_worker_state.py` | M |
| 2.4 | Add dependency check to `_add_plugin_tools` flow | `agent_worker_state.py` | S |
| 2.5 | Add security validation for dependency specifiers | `agent_worker_state.py` or `security_gate.py` | S |

**Estimated effort**: 1-2 days

### Phase 3: Unification and Documentation (Medium-term)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 3.1 | Tag `build_tools()` output with `_plugin_origin` | `registry.py` | S |
| 3.2 | Optionally route plugin tools through sandbox when deps exist | `agent_worker_state.py` | L |
| 3.3 | Document plugin tool contract (what to return, how deps work) | `docs/`, plugin README | M |
| 3.4 | Add plugin tool validation at registration time | `registry.py` | M |

**Estimated effort**: 2-3 days

### Phase 4: Testing

| # | Task | Scope | Effort |
|---|------|-------|--------|
| 4.1 | Unit test `_adapt_plugin_tool` with various tool types | `test_plugin_tool_adapter.py` | M |
| 4.2 | Unit test `_introspect_callable_parameters` | `test_plugin_tool_adapter.py` | S |
| 4.3 | Unit test `ToolResult.error()` / `ToolResult.success()` | `test_tool_result.py` | S |
| 4.4 | Integration test: plugin discovery -> tool loading -> execution | `test_plugin_integration.py` | L |
| 4.5 | Integration test: dependency installation flow | `test_plugin_deps.py` | M |
| 4.6 | End-to-end test: agent uses pdf-assistant plugin tools | `test_agent_pdf_plugin_e2e.py` | L |

**Estimated effort**: 2-3 days

---

## 5. Affected Files Summary

| File | Change Type | Description |
|------|------------|-------------|
| `src/infrastructure/agent/tools/result.py` | Modify | Add `error()` and `success()` factory classmethods |
| `src/infrastructure/agent/core/tool_converter.py` | Modify | Add `__call__` to `_resolve_execute_method` candidates |
| `src/infrastructure/agent/state/agent_worker_state.py` | Modify | Add `_adapt_plugin_tool`, `_introspect_callable_parameters`, update `_add_plugin_tools` |
| `src/infrastructure/agent/plugins/registry.py` | Modify | Tag tool objects with `_plugin_origin` in `build_tools()` |
| `src/infrastructure/agent/plugins/manifest.py` | Modify | Add `PluginDependencies` to `PluginManifestMetadata` |
| `.memstack/tools/pdf_tools.py` | Fix | Replace `ToolResult(error=...)` with `ToolResult(output=..., is_error=True)` |
| `.memstack/plugins/pdf-assistant/memstack.plugin.json` | Modify | Add `dependencies` section |
| `memstack_tools/__init__.py` | Modify | Re-export `ToolResult.error`, `ToolResult.success`, update docs |

**New files**:
| File | Description |
|------|-------------|
| `src/infrastructure/agent/plugins/plugin_tool_adapter.py` | (Optional) Extract adapter logic to dedicated module |
| `src/tests/unit/test_plugin_tool_adapter.py` | Unit tests for adapter |
| `src/tests/integration/test_plugin_tool_pipeline.py` | Integration tests |

---

## 6. Migration and Backward Compatibility

| Change | Backward Compatible | Migration |
|--------|-------------------|-----------|
| `ToolResult.error()` / `ToolResult.success()` | Yes (additive) | None required |
| `__call__` in `_resolve_execute_method` | Yes (additive) | None required |
| `_adapt_plugin_tool` wrapper | Yes (existing ToolInfo pass through) | None required |
| `_introspect_callable_parameters` | Yes (fallback only when no schema declared) | None required |
| `PluginDependencies` in manifest | Yes (optional field, defaults to None) | Plugins can add `dependencies` at their own pace |
| `_plugin_origin` tag on tool objects | Yes (only set, never required) | None required |

All changes are backward compatible. Existing plugins continue to work. The adapter layer handles any raw object gracefully with fallbacks.

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `_introspect_callable_parameters` generates incorrect schema | Medium | Low | LLM can still call tools; worst case = wrong parameter types. Add validation. |
| Auto-installing dependencies introduces security risk | Medium | High | Validate specifiers against allowlist, use `--quiet` + timeout, log all installs |
| `__call__` resolution picks wrong method on some objects | Low | Medium | `__call__` is last in priority list, only used as fallback |
| Plugin tool adapter masks real errors | Low | Medium | Always log original exception, include in ToolResult output |
| Sandbox dependency path conflicts with host path | Low | Low | Each path is distinct and independently tested |

---

## 8. Open Questions

1. **Should `_adapt_plugin_tool` live in `agent_worker_state.py` or a new `plugin_tool_adapter.py`?**
   Recommendation: Extract to `plugin_tool_adapter.py` for testability and single responsibility. `agent_worker_state.py` is already 3294 lines.

2. **Should we deprecate `register_tool_factory()` in favor of a unified API?**
   Recommendation: Not yet. Keep both paths but document clearly. Unification can happen in a future version after the adapter pattern is proven.

3. **Should plugin tool parameter introspection use `typing.get_type_hints()` for richer type info?**
   Recommendation: Start with `inspect.signature()` (simpler, fewer edge cases). Enhance later if needed.

4. **Should dependency installation happen at plugin load time or first tool call time?**
   Recommendation: Plugin load time (in `_add_plugin_tools`). Failing early is better than failing at first user interaction.
