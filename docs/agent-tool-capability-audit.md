# Agent Tool Capability Audit

Last checked against code structure: 2026-06-23.

The test counts in "Current Evidence" are historical run records from the original audit;
rerun the listed commands before using those counts as current quality evidence.

## Objective

Make agent tools reliable and reduce the effort required to expose new system capabilities to
agents. The long-term target is that an agent can use the system's capabilities through stable,
policy-aware tools rather than ad hoc code or manual API workarounds.

## Current Evidence

| Area | Evidence | Status |
|---|---|---|
| Built-in tool behavior | `uv run pytest src/tests/unit/agent/tools src/tests/unit/infrastructure/agent/tools -q` | 794 passed |
| Tool registration and discovery | `uv run pytest src/tests/unit/services/test_sandbox_tool_registry.py src/tests/unit/application/services/test_tool_discovery.py src/tests/unit/application/services/test_sandbox_simplified_tools.py src/tests/unit/infrastructure/agent/core/test_tool_converter.py src/tests/unit/infrastructure/agent/core/test_tool_selection.py src/tests/unit/infrastructure/agent/core/test_execution_path_integration.py src/tests/unit/infrastructure/agent/processor/test_processor_tool_refresh.py src/tests/unit/infrastructure/agent/state/test_inject_discovered_mcp_tools.py src/tests/unit/infrastructure/agent/state/test_parallel_mcp_discovery.py src/tests/unit/infrastructure/agent/state/test_tool_discovery_retry.py src/tests/unit/infrastructure/mcp/test_incremental_tool_discovery.py -q` | 132 passed |
| Broad agent unit suite | `uv run pytest src/tests/unit/agent src/tests/unit/infrastructure/agent -q` | 4165 passed |
| Agent integration suite | `uv run pytest src/tests/integration/agent -q` | 95 passed |
| Agent definition policy parity | `src/infrastructure/agent/tools/agent_definition_tool.py` now supports agent definition capability fields already present in the REST API: skills, MCP servers, persona files, workspace config, spawn depth, retry policy, fallback models, metadata, session policy, and delegate config. | Closed for this pass |
| Agent definition regression tests | `src/tests/unit/agent/tools/test_agent_definition_tool.py` covers create/update with full capability policy fields. | Covered |
| System API bridge | `src/infrastructure/agent/tools/system_api.py` discovers `/api/*` OpenAPI operations and can call them with the current user's forwarded API key or an explicit agent API key environment fallback. | Added |
| System API bridge tests | `uv run pytest src/tests/unit/infrastructure/agent/tools/test_system_api_tool.py src/tests/unit/infrastructure/adapters/primary/web/websocket/test_chat_handler_preferred_language.py -q` | 7 passed |

## Capability Coverage Snapshot

| Capability family | Current agent entry point |
|---|---|
| Web/search | `web_search`, `web_scrape` |
| System API | `system_api` for listing, describing, and invoking `/api/*` OpenAPI operations through normal route auth |
| Memory and graph | `memory_search`, `memory_get`, `memory_create`, `memory_update`, `memory_delete`, plus memory runtime/plugin tools when enabled |
| Files, shell, code, terminal, desktop | Sandbox MCP wrappers and environment tools such as `terminal` and `desktop` |
| Skills | `skill`, `skill_loader`, `skill_installer`, `skill_sync` |
| Plugins and MCP | `plugin_manager`, `register_mcp_server`, `debug_mcp_server`, `create_mcp_server_from_template`, dynamic MCP tool adapters |
| Human input and secrets | `ask_clarification`, `request_decision`, `request_env_var`, `get_env_var`, `check_env_vars` |
| Tasks and workspace orchestration | Todo tools, workspace WTP tools, workspace chat tools, multi-agent action tools |
| Agents and subagents | `agent_definition_manage`, agent/session tools, delegation tools, subagent session tools |
| Runtime/model control | `list_available_models`, `switch_model_next_turn`, `session_status`, `structured_output`, verdict/reflection tools |

## Remaining Caveats

The prior REST capability gap is now covered by `system_api`, which uses the live OpenAPI route
contract and the current user's API authorization. Route-level dependencies remain the policy
boundary for tenant/project/user access.

Two caveats remain:

1. High-value, stable capabilities should still graduate to typed purpose-built tools when the
   agent needs richer semantics, events, or stricter policy metadata than a generic HTTP bridge can
   express.
2. Background agent runs that do not originate from an authenticated WebSocket/voice session need
   `MEMSTACK_AGENT_API_KEY` or `MEMSTACK_API_KEY` configured before `system_api.request` can call
   authenticated routes.

## New Tool Development Checklist

1. Add a focused `@tool_define` function for the capability, or register an MCP/plugin tool.
2. Keep the input schema explicit, typed, and policy-aware.
3. Put business logic in application services, not in the tool wrapper.
4. Add unit tests for success, validation errors, permission/policy behavior, and emitted events.
5. Add registration/discovery tests when the tool is loaded dynamically.
6. Update `docs/TOOLS.md` only when a new capability family or contract is introduced.
