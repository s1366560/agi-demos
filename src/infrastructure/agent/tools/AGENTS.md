# agent/tools/ — L1 Atomic Tool Implementations

## Purpose
- All tool implementations the agent can invoke (L1 layer)
- Two registration patterns coexist: legacy class-based and new decorator-based

## Two Registration Patterns

### Legacy: `AgentTool` class (DEPRECATED)
```python
class MyTool(AgentTool):
    _pending_events: list = []
    def execute(self, **kwargs) -> str: ...
    def consume_pending_events(self) -> list: ...
```
- Extends `AgentToolBase` with output truncation
- Events emitted via `_pending_events` list + `consume_pending_events()`
- Processor calls `tool_def._tool_instance.consume_pending_events()` post-execute

### New: `@tool_define` decorator (PREFERRED)
```python
@tool_define(name="my_tool", description="...", parameters={...})
async def my_tool(ctx: ToolContext, **kwargs) -> ToolResult: ...
```
- Creates `ToolInfo` registered in module-level `_TOOL_REGISTRY`
- Events emitted via `ctx.emit(event_dict)` — no manual consume needed
- Returns `ToolResult` instead of raw string
- DI via module-level `configure_*()` functions (e.g., `configure_terminal()`)

## Tool Categories

| Category | Files | Notes |
|----------|-------|-------|
| Task management | `todo_tools.py` | Both legacy + new patterns as reference |
| Sandbox | `terminal_tool.py`, `desktop_tool.py` | Shell/UI execution |
| Interaction | `clarification_tool.py`, `decision_tool.py` | HITL triggers |
| Memory | `memory_tools.py` | Recall/store memories |
| Environment | `env_var_tools.py` | Get/request env vars |
| Plugin | `plugin_manager.py`, `plugin_tools.py` | Plugin CRUD |
| MCP | `register_mcp_server.py`, `debug_mcp_server.py` | MCP server management |
| Skill | `skill_tool.py`, `skill_loader.py`, `skill_installer.py` | Skill CRUD |
| Plan | `plan_tools.py` | Plan enter/update/exit |
| Self-modifying | `mutation_ledger.py`, `mutation_transaction.py` | Agent self-modification |

## ToolContext (context.py)
- Dataclass carrying: session_id, message_id, call_id, agent_name, conversation_id, abort_signal, project_id, user_id
- `ctx.emit(event_dict)` replaces `_pending_events` pattern
- Passed as first arg to all `@tool_define` functions

## DI Pattern for New Tools
- Module-level `configure_*()` function injects dependencies via closure
- Called during agent init, returns configured tool callable
- Example: `configure_terminal(sandbox_adapter)` returns terminal tool with adapter bound

## Adding a New Tool (Checklist)
1. Create file in this directory
2. Use `@tool_define` decorator with name, description, parameters schema
3. Accept `ToolContext` as first parameter
4. Return `ToolResult` (not raw string)
5. Use `ctx.emit()` for SSE events (if needed)
6. Add `configure_*()` function if DI required
7. Register in tool pipeline (react_agent.py init phase)

## Gotchas
- `_TOOL_REGISTRY` is module-level — import side-effects register tools
- Legacy tools: `AgentTool.execute()` returns str; new tools return `ToolResult`
- Output truncation only in legacy `AgentTool` base class — new tools must handle own limits
- `todo_tools.py` has BOTH patterns — use as migration reference
- Tool visibility can be toggled — `_is_tool_visible_to_model` in tool_converter.py
