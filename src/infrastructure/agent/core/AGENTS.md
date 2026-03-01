# agent/core/ — ReAct Engine & Agent Lifecycle

## Purpose
- Houses the ReAct reasoning loop, project-scoped agent wrapper, and tool conversion layer
- Entry point: `react_agent.py` (ReActAgent), wrapped by `project_react_agent.py` (ProjectReActAgent)

## Key Files

| File | Role |
|------|------|
| `react_agent.py` | ReActAgent — main reasoning loop, 8-phase `__init__`, `stream()` generator |
| `project_react_agent.py` | ProjectReActAgent — lifecycle wrapper (initialize/execute_chat/pause/resume/stop) |
| `tool_converter.py` | `convert_tools()` — wraps AgentToolBase and ToolInfo into ToolDefinition |
| `tool_selector.py` | Tool selection pipeline — semantic/keyword/embedding backends, policy layers |
| `doom_loop_detector.py` | Detects stuck loops (repeated tool calls, no progress) |
| `cost_tracker.py` | Token/cost tracking per conversation |
| `streaming.py` | LLM stream event handling (TEXT_*, REASONING_*, TOOL_CALL_*) |

## ReActAgent Init Phases (in order)
1. `_init_tool_pipeline` — tool selection backends + policy
2. `_init_memory_hooks` — memory recall/capture callbacks
3. `_init_prompt_and_context` — system prompt, workspace persona loading
4. `_init_execution_config` — max iterations, retry policy
5. `_init_skill_system` — skill orchestrator + skill tools
6. `_init_subagent_system` — SubAgentRouter, SubAgentSessionRunner, SubAgentToolBuilder
7. `_init_orchestrators` — skill + subagent orchestrators
8. `_init_background_services` — background task handlers

## Hot-Plug Tools
- `tool_provider` callable is invoked at each `stream()` call
- Returns fresh tool list — enables MCP tool refresh without restart
- `convert_tools()` re-runs every cycle to rebuild ToolDefinition map

## Domain Lane Routing
- `_DOMAIN_LANE_RULES` maps keywords to lanes: plugin, mcp, governance, code, data
- Used to pre-filter tools before LLM selection
- Falls back to full tool set if no lane matches

## ProjectAgentManager
- Manages multiple ProjectReActAgent instances (one per project)
- LRU eviction when capacity exceeded
- WebSocket notifications for agent state changes (running/paused/stopped)
- MCP tool refresh detection triggers tool pipeline rebuild

## Gotchas
- `convert_tools()` output is ToolDefinition, NOT original tool class
- Access original tool via `tool_def._tool_instance`
- `tool_def.execute` is a closure wrapper, not the raw tool.execute method
- Visibility filtering (`_is_tool_visible_to_model`) can hide tools from LLM
- Tool summaries are applied during conversion — tool descriptions may differ from source
