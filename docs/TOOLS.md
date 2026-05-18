# MemStack Agent Tool System

This document describes the current agent tool architecture and the maintained tool
families. It replaces older lists that referenced removed `plan_enter`, `plan_update`, and
`plan_exit` tool files.

Last checked against code: 2026-05-18.

## Source Of Truth

| Concern | Source |
|---|---|
| Tool definition decorator | `src/infrastructure/agent/tools/define.py` |
| Built-in tools | `src/infrastructure/agent/tools/*.py` |
| Tool provider/runtime wiring | `src/infrastructure/agent/tools/tool_provider.py`, `pipeline.py`, `executor.py` |
| Tool conversion for LLM calls | `src/infrastructure/agent/core/tool_converter.py` |
| Sandbox MCP wrapper | `src/infrastructure/agent/tools/sandbox_tool_wrapper.py` |
| Plugin tools | `src/infrastructure/agent/tools/plugin_tools.py`, `plugin_manager.py` |
| Sandbox server tools | `sandbox-mcp-server/src/tools/` |
| Runtime catalog API | `GET /api/v1/agent/tools`, `GET /api/v1/agent/tools/capabilities` |

The runtime catalog is more authoritative than this document for enabled tools because
plugins, MCP servers, custom tools, tenant configuration, and sandbox availability can change
the final list.

## Architecture

```text
ReAct/session processor
  -> tool conversion and policy checks
  -> ToolPipeline / ToolExecutor
  -> ToolInfo from @tool_define, plugins, MCP, or sandbox wrappers
  -> ToolResult + optional ToolEvent
  -> domain event conversion
  -> WebSocket / persistence / UI timeline
```

Tool definitions use `@tool_define` and return `ToolInfo` objects. Dynamic providers can add
plugin tools, MCP server tools, and sandbox tools without editing the static built-in list.

## Built-In Tool Families

| Family | Representative tools | Purpose |
|---|---|---|
| Search and web | `web_search`, `web_scrape` | External search and rendered page extraction. |
| System API | `system_api` | Discover and call MemStack HTTP API operations with current-user API authorization. |
| Memory | `memory_search`, `memory_get`, `memory_create`, `memory_update`, `memory_delete` | Project memory lookup and mutation through application services. |
| HITL | `ask_clarification`, `request_decision`, `request_env_var`, `check_env_vars`, `get_env_var` | Pause for human clarification, decision, environment variables, or secret lookup. |
| Todo/task | `todoread`, `todowrite` | Session task list updates that emit task events. |
| Agent definitions | `agent_definition_manage` | Create, inspect, update, and delete agent definitions, including tool/skill/MCP/workspace/session/delegation policy fields. |
| Delegation | `delegate_to_subagent`, `parallel_delegate_subagents`, `agent_spawn`, `agent_send`, `agent_stop`, `agent_list`, `agent_history`, `agent_sessions` | Subagent and multi-agent execution support. |
| Session communication | `sessions_list`, `sessions_history`, `sessions_send`, `sessions_*_v2`, `subagents_v2` | Conversation/session-level coordination and nested session tools. |
| Workspace | `workspace_assign_task`, `workspace_cancel_task`, `workspace_report_progress`, `workspace_report_complete`, `workspace_report_blocked`, `workspace_chat_send`, `workspace_chat_read`, `workspace_request_clarification`, `workspace_respond_clarification`, `workspace_health_verdict` | Workspace plan/task collaboration and WTP reporting. |
| Multi-agent action | `assign_task`, `refuse_task`, `request_human_input`, `escalate`, `mark_conflict`, `declare_progress`, `signal_goal_complete` | Structured inter-agent action events. |
| Skills | `skill`, `skill_loader`, `skill_installer`, `skill_sync` | Load, install, sync, or invoke skills. |
| Plugins/MCP | `plugin_manager`, `register_mcp_server`, `debug_mcp_server`, `create_mcp_server_from_template` | Runtime plugin and MCP server management. |
| Runtime/model | `list_available_models`, `switch_model_next_turn`, `session_status`, `structured_output`, `reflect_friction`, `verdict`, `handoff`, `cron` | Runtime introspection, structured outputs, review/verdicts, and scheduled actions. |
| Environment UI | `terminal`, `desktop` | Web terminal and remote desktop service management. |

## Plan Mode Status

Historical docs referenced built-in tools named `plan_enter`, `plan_update`, and
`plan_exit`. Those tool files are not present in the current `src/infrastructure/agent/tools`
tree. Current plan-related behavior is exposed through:

- Agent REST routes under `/api/v1/agent/plan/*`.
- Workspace plan routes under `/api/v1/workspaces/{workspace_id}/plan/*`.
- Workspace planning contract tools in
  `src/infrastructure/agent/tools/workspace_planning_contract.py` and
  `workspace_plan_contract_tools.py`.
- Frontend plan/workspace state in `web/src/stores/planReviewStore.ts`,
  `web/src/stores/agent/*`, and workspace components.

Do not add new documentation that tells agents to call `plan_enter`, `plan_update`, or
`plan_exit` unless those tools are reintroduced in code.

## Sandbox Tools

The sandbox tool surface is delivered through MCP wrappers and `sandbox-mcp-server`.
Representative families:

| Family | Examples | Notes |
|---|---|---|
| File | `read`, `write`, `edit`, `glob`, `grep`, `list`, `patch` | Workspace-scoped file operations. |
| Shell | `bash` | Non-interactive command execution with timeout and output limits. |
| Artifact | `export_artifact`, `list_artifacts`, `batch_export_artifacts` | Export files to MemStack artifact storage. |
| Terminal | `start_terminal`, `stop_terminal`, `get_terminal_status`, `restart_terminal` | ttyd-backed terminal service. |
| Desktop | `start_desktop`, `stop_desktop`, `get_desktop_status`, `restart_desktop` | XFCE/TigerVNC/noVNC desktop service. |
| Browser/preview | HTTP preview and browser automation helpers where enabled. |
| Code/test | Code-intelligence, testing, coverage, and project command helpers where enabled. |

The exact sandbox catalog depends on the sandbox server version and enabled profile. Inspect
`sandbox-mcp-server/src/tools/` or call the runtime tool listing endpoints for the live set.

## Permissions And Policy

Tool execution policy is layered:

- Static tool metadata declares names, descriptions, input schemas, and safety metadata.
- Runtime policy checks can allow, deny, or ask before execution.
- The `system_api` bridge uses the live OpenAPI contract and forwards the authenticated
  current-user API key when available; route dependencies still enforce tenant/user/project
  authorization.
- Sandbox wrapper policy classifies sensitive filesystem/shell/network actions.
- HITL tools and WebSocket/REST HITL routes carry user decisions back into the run.

Related code:

- `src/infrastructure/agent/permission/`
- `src/infrastructure/agent/tools/tool_mutation_guard.py`
- `src/infrastructure/agent/tools/mutation_ledger.py`
- `src/infrastructure/agent/tools/mutation_transaction.py`

## Events

Tools can emit domain events through pending-event patterns such as the todo tools. The
processor consumes those events and the event converter sends them to persistence and the web
timeline.

Important files:

- `src/infrastructure/agent/tools/todo_tools.py`
- `src/infrastructure/agent/processor/processor.py`
- `src/domain/events/agent_events.py`
- `src/domain/events/types.py`
- `src/infrastructure/agent/events/converter.py`
- `web/src/services/agent/messageRouter.ts`
- `web/src/stores/agent/*`

See [agent-event-types.md](agent-event-types.md) for current event names.

## Extending Tools

Preferred path for a new built-in tool:

1. Add a focused `@tool_define` function in `src/infrastructure/agent/tools/`.
2. Keep the schema explicit and typed.
3. Put business logic in application services when the tool touches domain state.
4. Add policy metadata for mutating, external, or sensitive operations.
5. Add focused unit tests for validation and failure behavior.
6. Update this document only if the tool creates a new family or changes the contract.

For custom tools, use the dynamic loader conventions in
`src/infrastructure/agent/tools/custom_tool_loader.py`; for plugin tools, use plugin runtime
registration rather than hardcoding imports.

## Operational Checks

```bash
# Static tool definitions
rg -n '@tool_define|name="' src/infrastructure/agent/tools -g '*.py'

# Runtime catalog, when the API is running
curl -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/api/v1/agent/tools

curl -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/api/v1/agent/tools/capabilities
```

## Historical Notes

Some older planning/audit documents still mention removed or migrated tools. Treat this page
and the source files above as the current contract.
