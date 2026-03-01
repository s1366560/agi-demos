# mcp/ -- Model Context Protocol Infrastructure

## Purpose
MCP client infrastructure: transport layer, tool discovery/registry, connection pooling, and execution pipeline.

## Key Files
- `tool_registry.py` (244 lines) -- SHA256 hash-based incremental tool discovery
- `pipeline_executor.py` (108 lines) -- abort-aware MCP tool execution with error handling
- `sandbox_tool_adapter.py` -- bridges sandbox tools to MCP protocol
- `config.py` -- MCP configuration constants
- `health_monitor.py` -- MCP server health monitoring
- `validation.py` -- request/response validation

## Directory Structure
- `clients/` -- MCP client implementations (websocket, http, subprocess, connection pool)
- `transport/` -- transport layer abstraction (base, factory, http, stdio, websocket)
- `tools/` -- tool abstraction (base, factory)

## Transport Types
| Transport | File | Use Case |
|-----------|------|----------|
| WebSocket | `transport/websocket.py` | Docker sandbox MCP servers |
| HTTP | `transport/http.py` | Remote MCP servers |
| Stdio | `transport/stdio.py` | Local subprocess MCP servers |

`transport/factory.py` selects transport based on server config.

## Tool Registry (tool_registry.py)
- Keyed by `(sandbox_id, server_name)` tuple
- SHA256 hash of tool definitions for change detection
- Incremental sync: only re-registers tools when hash changes
- Avoids redundant tool registration on reconnect

## Pipeline Executor (pipeline_executor.py)
- Wraps MCP tool calls with abort awareness
- `MCPErrorHandler` categorizes errors: `connection_error`, `timeout`, `aborted`
- Checks abort flag between pipeline stages
- Returns structured error results (not exceptions) for tool failures

## Connection Pool (clients/mcp_connection_pool.py)
- Pools MCP WebSocket connections per sandbox
- Reuses connections across tool invocations
- Health check before returning connection from pool
- Auto-reconnect on stale connections

## Adding a New MCP Tool
1. Define tool schema in MCP server (sandbox side)
2. Tool auto-discovered by `tool_registry.py` on next sync
3. For custom client-side handling: add wrapper in `tools/`
4. Register in `tools/factory.py` if non-standard

## Gotchas
- Tool registry hash is in-memory -- full resync on app restart
- WebSocket transport has no built-in reconnection (connection pool handles it)
- Stdio transport spawns subprocess -- ensure binary exists on host
- `pipeline_executor.py` swallows tool errors into result dicts -- check `error` field in response
- MCP protocol version compatibility: server and client must agree on protocol version
- Connection pool does NOT limit max connections -- can exhaust file descriptors under load
