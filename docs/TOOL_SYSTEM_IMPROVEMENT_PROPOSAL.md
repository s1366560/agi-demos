# MemStack Tool System Improvement Proposal

> Based on comparative analysis of OpenCode (core), Oh-My-OpenCode (plugin layer), and MemStack (current project).

---

## Executive Summary

MemStack's tool system is functional but has accumulated organic complexity. By studying OpenCode's clean, composable architecture and Oh-My-OpenCode's hook/plugin layer, we identify **12 concrete improvement areas** that would make MemStack's tool system more maintainable, extensible, and aligned with modern agent platform patterns.

**Key takeaways:**
- OpenCode's tool system is notably simpler despite supporting more features (plugins, hooks, skills-as-tools, subagent delegation, model-aware filtering, abort signals).
- The simplicity comes from **two core design choices**: (1) a single `Tool.define()` factory with Zod validation baked in, and (2) a unified wrapper layer in `resolveTools()` that handles permissions, hooks, and truncation in one place.
- MemStack distributes these concerns across 5+ classes (`AgentToolBase`, `AgentTool`, `ToolRegistry`, `ToolExecutor`, `ToolDefinition`, `tool_converter`), creating indirection that makes the system harder to reason about and extend.

---

## 1. Tool Definition Interface Redesign

### Current State (MemStack)

Tools inherit from a two-level class hierarchy:

```
AgentToolBase (domain port, ABC)
  -> AgentTool (infrastructure, adds truncation)
    -> ConcreteTools (terminal_tool, todo_tools, etc.)
```

Each tool must implement:
- `name` property
- `description` property  
- `get_parameters_schema()` -> raw JSON dict
- `execute(arguments)` -> str

Problems:
- **No schema validation at definition time.** Parameters are raw dicts; typos in JSON schema silently pass.
- **Two base classes** (domain port vs infrastructure) create confusion about which to extend.
- **Tool conversion** happens externally in `tool_converter.py`, wrapping instances into `ToolDefinition` dataclass. This is an extra indirection layer that OpenCode avoids entirely.

### OpenCode Pattern

```typescript
// Single factory, schema validated at definition time
const ReadTool = Tool.define("read", async () => ({
  description: "Read a file",
  parameters: z.object({
    filePath: z.string().describe("Absolute path to file"),
    offset: z.number().optional(),
    limit: z.number().optional(),
  }),
  async execute(args, ctx) {
    // args is already validated and typed via Zod
    return { output: content, title: filePath };
  },
}));
```

Key differences:
- **Lazy `init()` pattern**: Tool definitions are functions that return tool config. This enables per-session initialization (e.g., different parameters based on model capabilities).
- **Zod schema = validation + JSON schema + TypeScript types** in one declaration.
- **No separate converter**: The tool IS its definition. No wrapping needed.

### Proposed Design

```python
from pydantic import BaseModel, Field
from typing import AsyncIterator
from src.infrastructure.agent.tools.context import ToolContext

class ReadFileParams(BaseModel):
    """Read a file from disk."""
    file_path: str = Field(description="Absolute path to the file")
    offset: int = Field(default=1, description="Line number to start from")
    limit: int = Field(default=2000, description="Max lines to read")

@tool_define(
    name="read",
    permission="read",  # Permission category
)
async def read_tool(params: ReadFileParams, ctx: ToolContext) -> ToolResult:
    """Read a file or directory from the local filesystem."""
    content = await read_file(params.file_path, params.offset, params.limit)
    return ToolResult(output=content, title=params.file_path)
```

**Changes:**
1. **Replace class hierarchy with `@tool_define` decorator.** Tools become decorated async functions. Pydantic model IS the parameter schema (auto-generates JSON schema, validates at call time, provides type hints).
2. **Eliminate `tool_converter.py`.** The decorator produces a `ToolInfo` object directly consumable by the processor. No external wrapping step.
3. **`ToolContext` replaces scattered dependencies.** Instead of tools accessing globals or receiving ad-hoc kwargs, a single context object provides session_id, message_id, abort_signal, metadata(), ask() (permissions), and agent info.
4. **`ToolResult` standardizes output.** Instead of returning raw strings, tools return structured results with `output`, `title`, `metadata`, `attachments`.

**Migration path:** Keep `AgentToolBase` as a compatibility shim that wraps legacy class-based tools into the new `ToolInfo` format. New tools use `@tool_define`. Deprecate class-based tools over time.

---

## 2. Unified Tool Execution Wrapper

### Current State (MemStack)

Tool execution logic is scattered across:
- `SessionProcessor._execute_tool()` — doom loop, permission checks, event coordination
- `ToolExecutor.execute()` — permission, doom loop (again), validation, sanitization, artifacts
- `tool_converter.py execute_wrapper` — sync/async normalization
- `AgentTool._truncate_output()` — per-tool truncation

This creates duplication (doom loop checked in two places) and makes it hard to add cross-cutting concerns.

### OpenCode Pattern

`resolveTools()` in `session/prompt.ts` creates a **single wrapper** around every tool:

```
resolveTools() wrapper:
  1. Plugin.trigger("tool.execute.before")  // Pre-hooks
  2. ctx.ask(permission)                     // Permission check
  3. tool.execute(args, ctx)                 // Actual execution
  4. Truncate.output(result)                 // Truncation
  5. Plugin.trigger("tool.execute.after")    // Post-hooks
  6. Return structured result
```

Everything happens in one place. No scattered logic.

### Proposed Design

Create a single `ToolPipeline` that wraps every tool execution:

```python
class ToolPipeline:
    """Single execution wrapper for all tools."""

    def __init__(
        self,
        permission_manager: PermissionManager,
        doom_detector: DoomLoopDetector,
        truncator: OutputTruncator,
        hooks: ToolHookRegistry,
    ):
        self._permission = permission_manager
        self._doom = doom_detector
        self._truncator = truncator
        self._hooks = hooks

    async def execute(
        self,
        tool: ToolInfo,
        args: dict,
        ctx: ToolContext,
    ) -> AsyncIterator[ToolEvent]:
        # 1. Pre-hooks (plugin system)
        args = await self._hooks.run_before(tool.name, args, ctx)

        # 2. Doom loop check
        if self._doom.is_stuck(tool.name, args):
            yield ToolEvent.doom_loop(tool.name)
            return

        # 3. Permission check
        decision = await self._permission.evaluate(tool.permission, ctx)
        if decision == PermissionAction.DENY:
            yield ToolEvent.denied(tool.name)
            return
        if decision == PermissionAction.ASK:
            yield ToolEvent.permission_asked(tool.name)
            approved = await self._permission.ask(tool.name, ctx)
            if not approved:
                yield ToolEvent.denied(tool.name)
                return

        # 4. Execute
        yield ToolEvent.started(tool.name, args)
        result = await tool.execute(args, ctx)

        # 5. Truncate
        result = self._truncator.truncate(result)

        # 6. Post-hooks
        result = await self._hooks.run_after(tool.name, result, ctx)

        # 7. Process artifacts
        artifacts = self._extract_artifacts(result)

        yield ToolEvent.completed(tool.name, result, artifacts)
```

**Benefits:**
- Doom loop logic lives in ONE place (remove from both `SessionProcessor` and `ToolExecutor`).
- Adding new cross-cutting concerns (rate limiting, cost tracking, telemetry) = add one step to the pipeline.
- `SessionProcessor` becomes simpler: it just calls `ToolPipeline.execute()` and yields the events.

---

## 3. Tool Hook System

### Current State (MemStack)

No hook/middleware system exists. Cross-cutting concerns are hardcoded into the processor and executor.

### OpenCode + Oh-My-OpenCode Pattern

Two-level hook system:
1. **Plugin hooks** (OpenCode): `tool.execute.before` / `tool.execute.after` — TypeScript functions registered by plugins that can modify args, block execution, or annotate results.
2. **External hooks** (Oh-My-OpenCode): Shell command hooks that run external processes (e.g., linters, security scanners) and return structured JSON decisions (allow/deny/ask).

### Proposed Design

```python
class ToolHookRegistry:
    """Registry for pre/post tool execution hooks."""

    def register_before(
        self,
        hook: Callable[[str, dict, ToolContext], Awaitable[dict | HookDecision]],
        pattern: str = "*",  # Tool name glob pattern
        priority: int = 100,
    ) -> None: ...

    def register_after(
        self,
        hook: Callable[[str, ToolResult, ToolContext], Awaitable[ToolResult]],
        pattern: str = "*",
        priority: int = 100,
    ) -> None: ...

    async def run_before(self, tool_name: str, args: dict, ctx: ToolContext) -> dict | HookDecision:
        """Run all matching before-hooks. Returns modified args or a decision (deny/ask)."""
        ...

    async def run_after(self, tool_name: str, result: ToolResult, ctx: ToolContext) -> ToolResult:
        """Run all matching after-hooks. Returns modified result."""
        ...
```

**Use cases enabled:**
- Security scanning before terminal commands (like Oh-My-OpenCode's `PreToolUse`)
- Audit logging after every tool execution
- Argument sanitization (e.g., stripping secrets from terminal args)
- Cost tracking hooks
- Plugin-provided tool transformations

---

## 4. Permission System Improvements

### Current State (MemStack)

`PermissionManager` supports 3 levels (allow/deny/ask) with mode-based defaults (BUILD/PLAN/EXPLORE). Session-scoped approvals. SSE event publishing for user prompts.

**Gaps vs OpenCode:**
- No **pattern-based rules**. OpenCode's `PermissionNext` supports glob patterns: `bash(command: "git *")` -> allow, `bash(command: "rm -rf *")` -> ask.
- No **persistent approval storage**. OpenCode stores "always allow" decisions that persist across sessions.
- No **ruleset composition**. OpenCode composes agent-level + user-level + session-level rules with last-match-wins semantics.
- No **tool disabling via permissions**. OpenCode's `disabled()` helper removes tools entirely from the LLM's tool list based on permission rules (tool never offered to the model).

### Proposed Design

```python
@dataclass
class PermissionRule:
    """A single permission rule with pattern matching."""
    permission: str           # e.g., "bash", "write", "read"
    pattern: str              # Glob pattern on args, e.g., "command:git *"
    action: PermissionAction  # ALLOW, DENY, ASK
    scope: RuleScope          # AGENT, USER, SESSION

class PermissionRuleset:
    """Composable permission ruleset with last-match-wins evaluation."""
    rules: list[PermissionRule]

    def evaluate(self, permission: str, args: dict) -> PermissionAction:
        """Evaluate rules in order; last match wins."""
        result = PermissionAction.ASK  # default
        for rule in self.rules:
            if rule.matches(permission, args):
                result = rule.action
        return result

    def disabled_tools(self, tools: list[ToolInfo]) -> set[str]:
        """Return tool names that should be hidden from the LLM."""
        ...

class PermissionManager:
    """Enhanced permission manager with rulesets and persistence."""

    def __init__(
        self,
        agent_rules: PermissionRuleset,
        user_rules: PermissionRuleset,
        persistent_store: PermissionStore,
    ):
        self._rulesets = [agent_rules, user_rules]
        self._session_rules = PermissionRuleset(rules=[])
        self._store = persistent_store

    async def evaluate(self, permission: str, args: dict, ctx: ToolContext) -> PermissionAction:
        """Evaluate all rulesets. Check persistent approvals first."""
        # Check persistent "always allow" approvals
        if await self._store.is_approved(permission, args):
            return PermissionAction.ALLOW

        # Evaluate rulesets (agent -> user -> session, last match wins)
        for ruleset in [*self._rulesets, self._session_rules]:
            action = ruleset.evaluate(permission, args)
            if action != PermissionAction.ASK:
                return action
        return PermissionAction.ASK

    async def approve(
        self,
        permission: str,
        pattern: str,
        scope: ApprovalScope,  # ONCE, SESSION, ALWAYS
    ) -> None:
        """Store an approval decision."""
        if scope == ApprovalScope.ALWAYS:
            await self._store.save(permission, pattern)
        elif scope == ApprovalScope.SESSION:
            self._session_rules.rules.append(
                PermissionRule(permission, pattern, PermissionAction.ALLOW, RuleScope.SESSION)
            )
```

**Key improvements:**
- Pattern-based rules enable fine-grained control (`bash(command: "git *")` allowed, `bash(command: "rm -rf /")` denied).
- Persistent approvals reduce user friction ("always allow read" survives across sessions).
- Tool disabling prevents the LLM from even seeing dangerous tools in certain modes.

---

## 5. Truncation System Enhancement

### Current State (MemStack)

`OutputTruncator` in `base.py` truncates by byte size (`MAX_OUTPUT_BYTES`). `ToolExecutor` also has `_MAX_TOOL_OUTPUT_BYTES`. No disk persistence. No direction-aware truncation.

### OpenCode Pattern

`Truncate` namespace provides:
- **MAX_LINES** (2000) and **MAX_BYTES** (50KB) limits
- **Disk persistence**: Full output saved to a temp file; truncated version returned to LLM with a hint about the full file location
- **Scheduled cleanup**: Files older than 7 days auto-deleted
- **Direction-aware**: Truncates from end by default, but keeps beginning for task tool results
- **Task-tool-aware hints**: When output is truncated, adds guidance about using grep/read to access specific sections

### Proposed Design

```python
@dataclass
class TruncationResult:
    """Result of truncating tool output."""
    output: str           # Truncated content
    was_truncated: bool
    original_lines: int
    original_bytes: int
    full_output_path: str | None  # Path to full output on disk

class OutputTruncator:
    MAX_LINES = 2000
    MAX_BYTES = 51200  # 50KB

    def __init__(self, output_dir: Path = Path("/tmp/memstack-tool-output")):
        self._output_dir = output_dir

    def truncate(
        self,
        output: str,
        direction: TruncateDirection = TruncateDirection.TAIL,
        tool_name: str | None = None,
    ) -> TruncationResult:
        lines = output.split("\n")
        byte_size = len(output.encode("utf-8"))

        if len(lines) <= self.MAX_LINES and byte_size <= self.MAX_BYTES:
            return TruncationResult(output=output, was_truncated=False, ...)

        # Save full output to disk
        full_path = self._save_to_disk(output, tool_name)

        # Truncate based on direction
        if direction == TruncateDirection.TAIL:
            truncated = "\n".join(lines[:self.MAX_LINES])
        else:
            truncated = "\n".join(lines[-self.MAX_LINES:])

        # Add hint about full output
        hint = self._build_hint(full_path, tool_name, len(lines), byte_size)
        return TruncationResult(
            output=f"{truncated}\n\n{hint}",
            was_truncated=True,
            original_lines=len(lines),
            original_bytes=byte_size,
            full_output_path=str(full_path),
        )

    def _build_hint(self, path: str, tool_name: str | None, lines: int, bytes: int) -> str:
        return (
            f"[Output truncated: {lines} lines, {bytes} bytes. "
            f"Full output saved to {path}. "
            f"Use grep to search or read with offset/limit to view specific sections.]"
        )

    @classmethod
    def cleanup_old_files(cls, max_age_days: int = 7) -> int:
        """Remove output files older than max_age_days. Call periodically."""
        ...
```

**Centralize truncation**: Remove it from `AgentTool` base class and `ToolExecutor`. It happens once, in `ToolPipeline`, after execution and before result is fed back to LLM.

---

## 6. ToolContext: Unified Execution Context

### Current State (MemStack)

Tools receive arguments as a dict. They access session state, emit events, and request permissions through various scattered mechanisms:
- `_pending_events` list (manually managed per tool)
- Direct imports of global singletons
- Constructor-injected dependencies (inconsistent)

### OpenCode Pattern

Every tool receives a `Tool.Context` with:
- `sessionID`, `messageID`, `callID` — identity
- `agent` — current agent info
- `abort` — AbortSignal for cancellation
- `messages` — conversation history
- `metadata(data)` — emit real-time UI metadata updates
- `ask(request)` — request permission (blocks until user responds)

### Proposed Design

```python
@dataclass
class ToolContext:
    """Unified context passed to every tool execution."""
    session_id: str
    message_id: str
    call_id: str
    agent_name: str
    conversation_id: str

    # Cancellation
    abort_signal: asyncio.Event

    # Conversation access (read-only)
    messages: list[Message]

    # Real-time metadata emission (replaces _pending_events for metadata)
    async def metadata(self, data: dict) -> None:
        """Emit metadata update to the UI in real-time."""
        ...

    # Permission request (replaces direct PermissionManager access)
    async def ask(self, permission: str, description: str = "") -> bool:
        """Request user permission. Blocks until response."""
        ...

    # Event emission (replaces _pending_events pattern)
    async def emit(self, event: ToolEvent) -> None:
        """Emit a domain event (task update, artifact, etc.)."""
        ...
```

**Key change: Replace `_pending_events` with `ctx.emit()`.**

Current pattern (manual, error-prone):
```python
class TodoWriteTool:
    def __init__(self):
        self._pending_events = []

    async def execute(self, args):
        # ... do work ...
        self._pending_events.append(TaskListUpdatedEvent(...))
        return result

    def consume_pending_events(self):
        events = self._pending_events[:]
        self._pending_events.clear()
        return events
```

Proposed pattern (context-driven, automatic):
```python
@tool_define(name="todowrite")
async def todowrite_tool(params: TodoWriteParams, ctx: ToolContext) -> ToolResult:
    # ... do work ...
    await ctx.emit(TaskListUpdatedEvent(...))  # Emitted immediately, no manual consume
    return ToolResult(output="Tasks updated")
```

The processor no longer needs to know about `_pending_events` or `consume_pending_events()`. Events flow through `ctx.emit()` and are collected by the pipeline automatically.

---

## 7. Abort/Cancel Signal Propagation

### Current State (MemStack)

`SessionProcessor` has `_abort_event` (asyncio.Event) and `RunContext.abort_signal`. But tool-level abort is inconsistent — most tools don't check abort signals during execution.

### OpenCode Pattern

Every tool receives `ctx.abort` (AbortSignal). Long-running tools (bash, task) check it:
```typescript
async execute(args, ctx) {
    const proc = spawn(args.command);
    ctx.abort.addEventListener("abort", () => proc.kill());
    // ...
}
```

### Proposed Design

The `ToolContext.abort_signal` is already available. The improvement is:

1. **Enforce abort checking in `@tool_define`**: The decorator wraps execution with abort signal monitoring. If aborted during execution, raises `ToolAbortedError`.

2. **Provide helper for long-running tools**:
```python
@tool_define(name="terminal")
async def terminal_tool(params: TerminalParams, ctx: ToolContext) -> ToolResult:
    process = await asyncio.create_subprocess_shell(params.command)

    # Helper that races process completion against abort signal
    result = await ctx.race(
        process.communicate(),
        timeout=params.timeout,
    )
    return ToolResult(output=result.stdout)
```

3. **`ctx.race()`** runs the awaitable and cancels it if `abort_signal` is set or timeout expires.

---

## 8. Model-Aware Tool Selection

### Current State (MemStack)

Tool selection is model-agnostic. All tools are offered to all models. MCP visibility (`_meta.ui.visibility`) controls UI-only vs model-visible, but there's no model-specific tool selection.

### OpenCode Pattern

`ToolRegistry.tools(model, agent)` filters and adapts tools per model:
- Some models get `apply_patch` instead of `edit` (GPT models)
- Tool parameter schemas may be simplified for less capable models
- Agent-specific tool whitelists/blacklists

### Proposed Design

```python
class ToolRegistry:
    def get_tools(
        self,
        model: str | None = None,
        agent: str | None = None,
        permission_ruleset: PermissionRuleset | None = None,
    ) -> list[ToolInfo]:
        """Return tools filtered and adapted for the given model/agent."""
        tools = list(self._tools.values())

        # 1. Filter by agent whitelist/blacklist
        if agent:
            tools = self._filter_by_agent(tools, agent)

        # 2. Apply model-specific adaptations
        if model:
            tools = [self._adapt_for_model(t, model) for t in tools]

        # 3. Remove permission-disabled tools
        if permission_ruleset:
            disabled = permission_ruleset.disabled_tools(tools)
            tools = [t for t in tools if t.name not in disabled]

        return tools

    def _adapt_for_model(self, tool: ToolInfo, model: str) -> ToolInfo:
        """Apply model-specific tool adaptations."""
        # e.g., swap edit tool for apply_patch on certain models
        if tool.name == "edit" and "gpt" in model.lower():
            return self._tools.get("apply_patch", tool)
        return tool
```

---

## 9. Skills as Tools

### Current State (MemStack)

Skills and tools are separate systems. Skills have their own orchestrator, loader, sync mechanism. This creates parallel infrastructure for what is essentially the same concept: "something the LLM can invoke."

### OpenCode Pattern

Skills ARE tools. `SkillTool` is a regular tool that:
1. Loads skill content from `.md` files
2. Asks permission via `ctx.ask()`
3. Returns the skill content as tool output

The LLM decides when to invoke a skill, just like any other tool. No separate orchestration layer needed.

### Proposed Design

```python
@tool_define(name="skill", permission="skill")
async def skill_tool(params: SkillParams, ctx: ToolContext) -> ToolResult:
    """Load a skill to get specialized instructions for a task."""
    skill = await skill_loader.load(params.name)
    if not skill:
        return ToolResult(output=f"Skill '{params.name}' not found.")

    # Permission check
    approved = await ctx.ask(
        permission="skill",
        description=f"Load skill: {skill.name} - {skill.description}",
    )
    if not approved:
        return ToolResult(output="Skill loading denied by user.")

    return ToolResult(
        output=skill.content,
        title=f"Skill: {skill.name}",
        metadata={"skill_name": skill.name, "scope": skill.scope},
    )
```

**Impact:** The `SkillOrchestrator` can be simplified significantly. Skill trigger-matching (keyword/semantic/hybrid) remains, but it feeds into the standard tool selection pipeline rather than a parallel system.

---

## 10. Unified MCP Tool Adapter

### Current State (MemStack)

Two separate MCP tool adapters exist with inconsistent naming conventions:

```
MCPToolAdapter (agent/mcp/adapter.py)
  -> Names tools: mcp_{server_id}_{tool_name}     (single underscore)

SandboxMCPServerToolAdapter (mcp/sandbox_tool_adapter.py)
  -> Names tools: mcp__{server}__{tool}           (double underscore)

MCPTool.full_name (domain/model/mcp/tool.py)
  -> Uses: mcp__{server}__{tool}                 (double underscore)
```

Problems:
- **Tool name lookups fail across boundaries.** A tool registered as `mcp__server__tool` cannot be found by code looking for `mcp_server_tool`.
- **Both extend `AgentTool` but share no common base.** Code duplication for parameter conversion, result formatting, and error handling.
- **Manual JSON schema validation.** `MCPToolAdapter.validate_args()` manually maps JSON Schema types (string -> str, number -> int/float) with brittle type-checking code. `SandboxMCPServerToolAdapter` has no validation at all.

### OpenCode Pattern

OpenCode's `registry.ts` has `fromPlugin()` that converts plugin tool definitions to internal `Tool.Info` using the same `Tool.define` pattern as native tools:

```typescript
// Plugin tools use the same factory as native tools
const pluginTool = Tool.fromPlugin(pluginDef, {
  // Plugin-provided execute function
  execute: async (args, ctx) => { ... }
});

// All tools go through resolveTools() wrapper (hooks, permissions, truncation)
const tools = resolveTools(registry.getTools(), context);
```

Key insight: **No special adapter class needed.** Plugin tools are first-class citizens with identical execution semantics.

### Proposed Design

Unify both adapters into a single `MCPToolInfo` that works for external and sandbox MCP tools:

```python
from pydantic import BaseModel, create_model, Field
from typing import Any

class MCPToolInfo:
    """Unified MCP tool definition for both external and sandbox MCP servers."""

    def __init__(
        self,
        server_id: str,
        tool_name: str,
        description: str,
        parameters_schema: dict,  # JSON Schema from MCP server
        executor: MCPToolExecutorPort,  # Abstraction over transport
    ):
        self.server_id = server_id
        self.tool_name = tool_name
        # Consistent naming: always double underscore
        self.full_name = f"mcp__{server_id}__{tool_name}"
        self.description = description
        self._executor = executor
        # Auto-generate Pydantic model from JSON Schema
        self._params_model = self._schema_to_pydantic(parameters_schema)

    @staticmethod
    def _schema_to_pydantic(schema: dict) -> type[BaseModel]:
        """Convert JSON Schema to Pydantic model for validation."""
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        fields = {}
        for name, prop in properties.items:
            json_type = prop.get("type", "string")
            py_type = MCPToolInfo._json_type_to_python(json_type)
            description = prop.get("description", "")
            default = ... if name in required else None
            fields[name] = (py_type, Field(description=description, default=default))

        return create_model(f"MCPParams_{name}", **fields)

    @staticmethod
    def _json_type_to_python(json_type: str) -> type:
        mapping = {
            "string": str,
            "number": float,
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        return mapping.get(json_type, Any)

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        """Execute via the executor abstraction."""
        # Validate args using Pydantic
        validated = self._params_model(**args)

        # Execute through the executor port (external HTTP or sandbox WebSocket)
        result = await self._executor.call_tool(
            server_id=self.server_id,
            tool_name=self.tool_name,
            arguments=validated.model_dump(),
            ctx=ctx,  # For abort signal propagation
        )

        return ToolResult(
            output=result.content,
            title=f"{self.server_id}.{self.tool_name}",
            metadata={"server": self.server_id, "tool": self.tool_name},
        )
```

**Key improvements:**
1. **Single naming convention.** Always use double underscore `mcp__{server}__{tool}` matching the domain model.
2. **Pydantic validation.** Auto-generated Pydantic models from JSON Schema replace manual type checking.
3. **Executor abstraction.** `MCPToolExecutorPort` abstracts over transport (HTTP for external, WebSocket for sandbox).
4. **Unified with `@tool_define`.** MCP tools can be wrapped the same way as native tools:

```python
# MCP tools become regular ToolInfo instances
mcp_tool_info = ToolInfo(
    name=mcp_tool.full_name,
    description=mcp_tool.description,
    parameters=mcp_tool._params_model,  # Pydantic model
    execute=mcp_tool.execute,
    permission="mcp",  # Unified permission category
)
```

---

## 11. MCP Tools as First-Class Pipeline Citizens

### Current State (MemStack)

`SandboxMCPServerToolAdapter.execute()` bypasses the entire `ToolPipeline` flow:

```python
class SandboxMCPServerToolAdapter(AgentTool):
    async def execute(self, arguments: dict) -> str:
        # Direct call to sandbox - NO pipeline integration
        result = await self._sandbox_adapter.call_tool(
            server=self._server_name,
            tool=self._tool_name,
            arguments=arguments,
            timeout=self._timeout,
            # No abort signal, no permission check, no hooks
        )
        return result  # Raw string, not ToolResult
```

Problems:
- **No pre/post hooks.** Cannot audit, transform, or block MCP tool calls.
- **No permission integration.** MCP tools bypass the permission system entirely.
- **No truncation.** Large file reads or verbose bash output can exceed context limits.
- **No abort signal.** Long-running sandbox commands continue after user cancels.
- **Inconsistent error handling.** Returns `"Error: {msg}"` strings instead of structured `ToolResult`.

`MCPToolAdapter` (external MCP) has similar gaps: it returns `"MCP tool execution failed: {msg}"` strings on error.

### OpenCode Pattern

All tools in OpenCode go through the same `resolveTools()` wrapper:

```typescript
resolveTools() wrapper:
  1. Plugin.trigger("tool.execute.before")  // Pre-hooks
  2. ctx.ask(permission)                     // Permission check
  3. tool.execute(args, ctx)                 // Actual execution
  4. Truncate.output(result)                 // Truncation
  5. Plugin.trigger("tool.execute.after")    // Post-hooks
  6. Return structured result
```

Plugin tools (the MCP equivalent in OpenCode) receive the same treatment as native tools.

### Proposed Design

Route all MCP tool executions through the `ToolPipeline` established in Section 2:

```python
class MCPToolAdapter:
    """MCP tool that integrates with ToolPipeline."""

    def __init__(self, mcp_tool_info: MCPToolInfo):
        self._info = mcp_tool_info

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        """Called by ToolPipeline after hooks/permission checks."""
        return await self._info.execute(args, ctx)

    def to_tool_info(self) -> ToolInfo:
        """Register with the pipeline like any other tool."""
        return ToolInfo(
            name=self._info.full_name,
            description=self._info.description,
            parameters=self._info._params_model,
            execute=self.execute,
            permission="mcp",  # Unified permission category
        )
```

**Pipeline integration with abort signals:**

```python
class MCPSandboxExecutor(MCPToolExecutorPort):
    """Sandbox-specific executor with abort signal support."""

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict,
        ctx: ToolContext,  # Contains abort_signal
    ) -> MCPToolResult:
        # Create abortable task
        tool_task = asyncio.create_task(
            self._sandbox_adapter.call_tool(
                server=server_id,
                tool=tool_name,
                arguments=arguments,
            )
        )

        # Race against abort signal
        abort_task = asyncio.create_task(ctx.abort_signal.wait())

        done, pending = await asyncio.wait(
            [tool_task, abort_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel pending task
        for task in pending:
            task.cancel()

        if abort_task in done:
            # User cancelled - try to cancel sandbox operation
            await self._sandbox_adapter.cancel_operation(server_id)
            raise ToolAbortedError(f"MCP tool {tool_name} cancelled by user")

        return await tool_task
```

**Structured error handling:**

```python
class MCPErrorHandler:
    """Convert MCP errors to structured ToolResult."""

    @staticmethod
    def handle_error(server: str, tool: str, error: Exception) -> ToolResult:
        """Convert exceptions to ToolResult with consistent structure."""
        error_types = {
            ConnectionError: ("connection_error", "Failed to connect to MCP server"),
            TimeoutError: ("timeout", "MCP tool execution timed out"),
            ToolAbortedError: ("aborted", "Tool execution was cancelled"),
        }

        error_type, message = error_types.get(type(error), ("unknown", str(error)))

        return ToolResult(
            output=f"[{error_type.upper()}] {message}",
            title=f"Error: {server}.{tool}",
            metadata={
                "error_type": error_type,
                "server": server,
                "tool": tool,
                "original_error": str(error),
            },
            is_error=True,  # Flag for error handling
        )
```

**Benefits:**
- MCP tools get hooks, permissions, and truncation automatically through `ToolPipeline`.
- Abort signals propagate to sandbox operations, enabling true cancellation.
- Consistent structured error handling across all tool types.
- Large outputs are truncated with disk persistence hints (Section 5).

---

## 12. SRP: Separate Resource/UI Concerns from Tool Execution

### Current State (MemStack)

`SandboxMCPServerToolAdapter` mixes tool execution with HTML caching/prefetch logic:

```python
class SandboxMCPServerToolAdapter(AgentTool):
    """~326 lines including UI concerns."""

    def __init__(self, ...):
        # ... tool setup ...
        self._resource_cache: dict[str, str] = {}  # HTML cache

    async def execute(self, arguments: dict) -> str:
        # ... tool execution ...
        pass

    # === 100+ lines of UI/resource concerns mixed in ===

    async def fetch_resource_html(self, resource_uri: str) -> str | None:
        """Fetch HTML for UI preview. Mixed into tool adapter."""
        if resource_uri in self._resource_cache:
            return self._resource_cache[resource_uri]
        # Fetch, cache, return...

    async def _capture_html_from_content(self, content: str, mime_type: str) -> str | None:
        """Extract/preview HTML from tool output. UI concern."""
        # 40+ lines of HTML extraction logic

    async def prefetch_resource_html(self, arguments: dict) -> None:
        """Pre-fetch HTML for anticipated resources."""
        # Background prefetch for UI responsiveness

    def get_cache_stats(self) -> dict:
        """Return cache statistics for monitoring."""
        return {"size": len(self._resource_cache), "keys": list(self._resource_cache.keys())}
```

Problems:
- **Single Responsibility Principle violation.** The adapter does two things: execute MCP tools AND manage HTML resource caching for UI previews.
- **Tight coupling.** UI resource concerns change independently from tool execution logic, but they are entangled in one class.
- **Hard to test.** Cannot test tool execution without the caching logic, and vice versa.
- **Caching is tool-specific.** Other tools that might benefit from resource caching cannot reuse this logic.

### OpenCode Pattern

OpenCode separates concerns through composition:

```typescript
// Tool focuses on execution only
const WebSearchTool = Tool.define("web_search", async () => ({
  execute: async (args, ctx) => {
    const results = await search(args.query);
    return { output: formatResults(results) };
  }
}));

// UI previews are handled by a separate ResourcePreviewService
// that subscribes to tool events and fetches HTML independently
```

The tool does not know about UI previews. A separate service handles resource caching and preview generation.

### Proposed Design

Extract HTML caching into a dedicated `MCPResourceCache` service:

```python
@dataclass
class ResourceCacheEntry:
    """Cached resource with metadata."""
    content: str
    mime_type: str
    fetched_at: datetime
    ttl_seconds: int = 3600

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.fetched_at + timedelta(seconds=self.ttl_seconds)


class MCPResourceCache:
    """Dedicated service for MCP resource caching and preview generation.

    Separated from tool execution concerns. Can be used by any tool that
    produces previewable resources.
    """

    def __init__(self, max_size: int = 100, default_ttl: int = 3600):
        self._cache: dict[str, ResourceCacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()

    async def get(self, resource_uri: str) -> str | None:
        """Get cached resource if available and not expired."""
        async with self._lock:
            entry = self._cache.get(resource_uri)
            if entry and not entry.is_expired():
                return entry.content
            if entry and entry.is_expired():
                del self._cache[resource_uri]
            return None

    async def set(self, resource_uri: str, content: str, mime_type: str) -> None:
        """Cache a resource with LRU eviction."""
        async with self._lock:
            # LRU eviction if at capacity
            if len(self._cache) >= self._max_size and resource_uri not in self._cache:
                oldest = min(self._cache.keys(), key=lambda k: self._cache[k].fetched_at)
                del self._cache[oldest]

            self._cache[resource_uri] = ResourceCacheEntry(
                content=content,
                mime_type=mime_type,
                fetched_at=datetime.utcnow(),
                ttl_seconds=self._default_ttl,
            )

    async def prefetch(self, resource_uris: list[str], fetcher: Callable) -> None:
        """Background prefetch for anticipated resources."""
        for uri in resource_uris:
            if uri not in self._cache:
                try:
                    content, mime_type = await fetcher(uri)
                    await self.set(uri, content, mime_type)
                except Exception:
                    pass  # Prefetch failures are non-fatal

    def get_stats(self) -> dict:
        """Cache statistics for monitoring."""
        total = len(self._cache)
        expired = sum(1 for e in self._cache.values() if e.is_expired())
        return {
            "size": total,
            "expired": expired,
            "effective_size": total - expired,
        }

    async def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        async with self._lock:
            expired_keys = [k for k, e in self._cache.items() if e.is_expired()]
            for k in expired_keys:
                del self._cache[k]
            return len(expired_keys)
```

**Clean tool adapter using the cache service:**

```python
class SandboxMCPToolAdapter:
    """Simplified adapter focused ONLY on tool execution."""

    def __init__(
        self,
        mcp_tool_info: MCPToolInfo,
        resource_cache: MCPResourceCache | None = None,
    ):
        self._info = mcp_tool_info
        self._resource_cache = resource_cache  # Injected, not managed

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        """Execute the MCP tool through the pipeline."""
        # Just execution - no caching logic mixed in
        return await self._info.execute(args, ctx)

    def to_tool_info(self) -> ToolInfo:
        return ToolInfo(
            name=self._info.full_name,
            description=self._info.description,
            parameters=self._info._params_model,
            execute=self.execute,
            permission="mcp",
        )


class MCPResourcePreviewService:
    """Separate service for UI preview generation.

    Subscribes to tool execution events and fetches resources
    for UI previews independently of tool execution.
    """

    def __init__(self, resource_cache: MCPResourceCache):
        self._cache = resource_cache

    async def on_tool_result(self, tool_name: str, result: ToolResult) -> None:
        """Called after tool execution to extract and cache previewable resources."""
        # Extract resource URIs from tool output
        uris = self._extract_resource_uris(result.output)

        # Prefetch in background
        asyncio.create_task(self._cache.prefetch(uris, self._fetch_resource))

    async def _fetch_resource(self, uri: str) -> tuple[str, str]:
        """Fetch a single resource for caching."""
        # Implementation details...
        pass

    def _extract_resource_uris(self, output: str) -> list[str]:
        """Extract previewable resource URIs from tool output."""
        # Regex or parsing logic...
        pass
```

**Benefits:**
1. **Single Responsibility.** The adapter does one thing: execute MCP tools. The cache service does one thing: manage resource caching.
2. **Reusability.** `MCPResourceCache` can be used by other tools that produce previewable resources (web search, file read, etc.).
3. **Testability.** Each component can be tested in isolation.
4. **Independent evolution.** UI preview logic can change without touching tool execution logic.

---


## Implementation Roadmap

### Phase 1: Foundation (Low risk, high impact)

| Item | Effort | Impact | Description |
|------|--------|--------|-------------|
| `ToolContext` | Medium | High | Unified context object, replaces `_pending_events` pattern |
| `ToolResult` | Low | Medium | Structured return type for all tools |
| `ToolPipeline` | Medium | High | Single execution wrapper, consolidates scattered logic |
| Centralized truncation | Low | Medium | Move to pipeline, remove from base class and executor |
| MCP naming standardization | Low | Medium | Unify single/double underscore naming to `mcp__{server}__{tool}` |
| Pydantic MCP validation | Medium | High | Replace manual JSON schema validation with Pydantic models |

### Phase 2: Definition & Registration (Medium risk)

| Item | Effort | Impact | Description |
|------|--------|--------|-------------|
| `@tool_define` decorator | Medium | High | Pydantic-based tool definition, replaces class hierarchy |
| Eliminate `tool_converter.py` | Low | Medium | Tools self-describe; no external conversion |
| Model-aware tool selection | Low | Medium | Filter/adapt tools per model in registry |
| Abort signal propagation | Low | Medium | `ctx.race()` helper, enforce in decorator |
| MCP ToolPipeline integration | Medium | High | Route MCP tools through ToolPipeline (hooks, permissions, truncation) |

### Phase 3: Extensibility (Higher risk, strategic)

| Item | Effort | Impact | Description |
|------|--------|--------|-------------|
| Hook system | Medium | High | Pre/post tool execution hooks |
| Permission pattern matching | Medium | High | Glob-based rules, persistent approvals |
| Skills as tools | High | Medium | Simplify skill orchestration layer |
| Plugin tool integration | High | Medium | External plugin-provided tools |
| MCP resource cache separation | Medium | Medium | Extract HTML caching from adapter into `MCPResourceCache` service |

### Migration Strategy

1. **New tools** use `@tool_define` from day one.
2. **Existing tools** continue working via compatibility shim in `tool_define` that wraps `AgentToolBase` instances.
3. **Gradually migrate** high-traffic tools (terminal, read, write, edit) first.
4. **Deprecate** `AgentToolBase` class hierarchy once all tools are migrated.
5. **Never break** the processor: `ToolPipeline` produces the same events the processor already expects.

---

## Appendix A: Architecture Comparison

### Tool Definition Flow

```
OpenCode:
  Tool.define(name, init) -> Tool.Info -> resolveTools() wrapper -> AI SDK tool
  [1 step: definition IS the executable]

MemStack (current):
  AgentToolBase subclass -> AgentTool subclass -> tool_converter.convert_tools()
    -> ToolDefinition dataclass -> processor.tools dict -> to_openai_format()
  [3 steps: definition, wrapping, format conversion]

MemStack (proposed):
  @tool_define(name) async def tool(params, ctx) -> ToolInfo -> ToolPipeline -> processor
  [1 step: definition IS the executable, pipeline handles the rest]
```

### Execution Pipeline

```
OpenCode:
  LLM stream -> processor tool-call event
    -> resolveTools wrapper:
      -> Plugin.trigger("tool.execute.before")
      -> ctx.ask(permission)
      -> tool.execute(args, ctx)
      -> Truncate.output(result)
      -> Plugin.trigger("tool.execute.after")
    -> processor tool-result event -> back to LLM

MemStack (current):
  LLM stream -> processor._process_step TOOL_CALL_END
    -> processor._execute_tool:
      -> doom loop check (processor level)
      -> ToolExecutor.execute:
        -> doom loop check (executor level, duplicate)
        -> permission check
        -> argument validation
        -> tool_def.execute(args)  [via convert_tools wrapper]
        -> _sanitize_tool_output
        -> _process_artifacts
      -> consume_pending_events (manual per-tool)
    -> append to messages -> back to LLM

MemStack (proposed):
  LLM stream -> processor._process_step TOOL_CALL_END
    -> ToolPipeline.execute:
      -> hooks.run_before()
      -> doom_detector.check()
      -> permission.evaluate()
      -> tool.execute(args, ctx)  [direct, no wrapper indirection]
      -> truncator.truncate()
      -> hooks.run_after()
      -> yield ToolEvent (events auto-collected from ctx)
    -> append to messages -> back to LLM
```

### Event Emission

```
OpenCode:
  tool calls ctx.metadata() -> immediate Bus event -> UI update
  tool calls ctx.ask() -> Bus event -> user prompt -> response

MemStack (current):
  tool appends to self._pending_events -> processor calls consume_pending_events()
    -> processor yields domain events -> Redis stream -> WebSocket -> frontend

MemStack (proposed):
  tool calls ctx.emit(event) -> pipeline collects -> yields to processor
    -> Redis stream -> WebSocket -> frontend
  [Same backend plumbing, but tool-side API is cleaner]
```

---

## Appendix B: Files Affected

### Core (new files)

| File | Purpose |
|------|---------|
| `src/infrastructure/agent/tools/define.py` | `@tool_define` decorator and `ToolInfo` |
| `src/infrastructure/agent/tools/context.py` | `ToolContext` class |
| `src/infrastructure/agent/tools/result.py` | `ToolResult` dataclass |
| `src/infrastructure/agent/tools/pipeline.py` | `ToolPipeline` execution wrapper |
| `src/infrastructure/agent/tools/hooks.py` | `ToolHookRegistry` |
| `src/infrastructure/mcp/tool_info.py` | Unified `MCPToolInfo` for external/sandbox MCP tools |
| `src/infrastructure/mcp/resource_cache.py` | `MCPResourceCache` service for UI resource caching |
| `src/domain/ports/mcp/executor_port.py` | `MCPToolExecutorPort` abstraction for transport |

### Modified

| File | Change |
|------|--------|
| `src/infrastructure/agent/processor/processor.py` | Use `ToolPipeline` instead of inline execution logic |
| `src/infrastructure/agent/tools/executor.py` | Simplify or deprecate; logic moves to `ToolPipeline` |
| `src/infrastructure/agent/core/tool_converter.py` | Deprecate; tools self-describe |
| `src/infrastructure/agent/tools/base.py` | Keep as compatibility shim, remove truncation |
| `src/infrastructure/agent/permission/manager.py` | Add pattern matching, persistent approvals |
| `src/infrastructure/agent/tools/tool_registry.py` | Add model-aware selection, hook registration |
| `src/infrastructure/agent/tools/truncation.py` | Enhance with disk persistence, direction awareness |
| All tool files (`todo_tools.py`, `terminal_tool.py`, etc.) | Migrate from class to `@tool_define` (Phase 2-3) |
| `src/infrastructure/mcp/sandbox_tool_adapter.py` | Remove HTML caching; use unified adapter |
| `src/infrastructure/agent/mcp/adapter.py` | Standardize naming, add Pydantic validation |
| `src/infrastructure/adapters/secondary/sandbox/mcp_sandbox_adapter.py` | Add abort signal propagation support |

### Removed (eventual)

| File | Reason |
|------|--------|
| `src/infrastructure/agent/core/tool_converter.py` | Replaced by `@tool_define` self-description |
| `src/domain/ports/agent/agent_tool_port.py` | Replaced by `ToolInfo` protocol (or kept as minimal ABC) |
