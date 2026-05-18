# Agent Tool Capability Audit

Last checked: 2026-05-18

## Objective

Make agent tools reliable and reduce the effort required to expose new system capabilities to
agents. The long-term target is that an agent can use the system's capabilities through stable,
policy-aware tools rather than ad hoc code or manual API workarounds.

## Current Evidence

| Area | Evidence | Status |
|---|---|---|
| Built-in tool behavior | `uv run pytest src/tests/unit/agent/tools src/tests/unit/infrastructure/agent/tools -q` | 788 passed |
| Tool registration and discovery | `uv run pytest src/tests/unit/services/test_sandbox_tool_registry.py src/tests/unit/application/services/test_tool_discovery.py src/tests/unit/application/services/test_sandbox_simplified_tools.py src/tests/unit/infrastructure/agent/core/test_tool_converter.py src/tests/unit/infrastructure/agent/core/test_tool_selection.py src/tests/unit/infrastructure/agent/core/test_execution_path_integration.py src/tests/unit/infrastructure/agent/processor/test_processor_tool_refresh.py src/tests/unit/infrastructure/agent/state/test_inject_discovered_mcp_tools.py src/tests/unit/infrastructure/agent/state/test_parallel_mcp_discovery.py src/tests/unit/infrastructure/agent/state/test_tool_discovery_retry.py src/tests/unit/infrastructure/mcp/test_incremental_tool_discovery.py -q` | 132 passed |
| Agent definition policy parity | `src/infrastructure/agent/tools/agent_definition_tool.py` now supports agent definition capability fields already present in the REST API: skills, MCP servers, persona files, workspace config, spawn depth, retry policy, fallback models, metadata, session policy, and delegate config. | Closed for this pass |
| Agent definition regression tests | `src/tests/unit/agent/tools/test_agent_definition_tool.py` covers create/update with full capability policy fields. | Covered |

## Capability Coverage Snapshot

| Capability family | Current agent entry point |
|---|---|
| Web/search | `web_search`, `web_scrape` |
| Memory and graph | `memory_search`, `memory_get`, `memory_create`, `memory_update`, `memory_delete`, plus memory runtime/plugin tools when enabled |
| Files, shell, code, terminal, desktop | Sandbox MCP wrappers and environment tools such as `terminal` and `desktop` |
| Skills | `skill`, `skill_loader`, `skill_installer`, `skill_sync` |
| Plugins and MCP | `plugin_manager`, `register_mcp_server`, `debug_mcp_server`, `create_mcp_server_from_template`, dynamic MCP tool adapters |
| Human input and secrets | `ask_clarification`, `request_decision`, `request_env_var`, `get_env_var`, `check_env_vars` |
| Tasks and workspace orchestration | Todo tools, workspace WTP tools, workspace chat tools, multi-agent action tools |
| Agents and subagents | `agent_definition_manage`, agent/session tools, delegation tools, subagent session tools |
| Runtime/model control | `list_available_models`, `switch_model_next_turn`, `session_status`, `structured_output`, verdict/reflection tools |

## Remaining Gap

The system has many REST capability surfaces under `src/infrastructure/adapters/primary/web/routers`.
Agents do not currently have a single, policy-aware internal API tool that can safely invoke any
router capability by route contract. Coverage is instead implemented through purpose-built tool
families plus dynamic MCP/plugin/sandbox tools.

Before adding a generic internal API tool, the architecture needs one of these choices:

1. Generate typed agent tools from selected service/router contracts with explicit policy metadata.
2. Add a constrained internal API tool that can call only route contracts listed in an allowlisted
   manifest, with tenant/project/user context injected from `ToolContext`.
3. Keep purpose-built tools as the only supported path, and require every new system capability to
   declare its agent-facing tool at feature launch.

Recommended direction: option 1 for high-value stable capabilities, with option 2 reserved for
admin/debug builds. That keeps agent capability coverage auditable without granting an unrestricted
in-process API client.

## New Tool Development Checklist

1. Add a focused `@tool_define` function for the capability, or register an MCP/plugin tool.
2. Keep the input schema explicit, typed, and policy-aware.
3. Put business logic in application services, not in the tool wrapper.
4. Add unit tests for success, validation errors, permission/policy behavior, and emitted events.
5. Add registration/discovery tests when the tool is loaded dynamically.
6. Update `docs/TOOLS.md` only when a new capability family or contract is introduced.
