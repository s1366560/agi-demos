# sandbox/ -- Sandbox Adapter Layer

## Purpose
Two sandbox adapters for executing code in isolated environments. Both implement `SandboxPort`.

## Key Files
- `mcp_sandbox_adapter.py` (3069 lines) -- Docker container sandbox with MCP WebSocket
- `local_sandbox_adapter.py` (705 lines) -- tunnel-based connection to user's local machine
- `container_manager.py` (351 lines) -- extracted Docker lifecycle (create/start/stop/remove)
- `sandbox_instance.py` -- `MCPSandboxInstance` extends `SandboxInstance`

## Two Adapter Types

| Adapter | Communication | Use Case |
|---------|--------------|----------|
| `MCPSandboxAdapter` | WebSocket to Docker container | Cloud deployments |
| `LocalSandboxAdapter` | WebSocket via ngrok/Cloudflare tunnel | User's local machine |

## MCPSandboxAdapter Internals
- Creates Docker containers with `sandbox-mcp-server` image
- 3 exposed ports per container:
  - 18765: MCP WebSocket (tool execution)
  - 16080: Desktop (noVNC)
  - 17681: Terminal (ttyd)
- Container labels: `memstack.project_id`, `memstack.project.id` (for cleanup/discovery)
- State machine: CREATING -> READY -> BUSY -> READY (or ERROR/STOPPED)
- Max concurrent sandboxes: 10 (default)
- Resource limits: 2GB memory, 2 CPU cores per container

## LocalSandboxAdapter Internals
- Connects to user's local machine via ngrok or Cloudflare tunnel URL
- Heartbeat monitoring with exponential backoff reconnection
- No container management -- relies on user running local MCP server
- Tunnel URL stored in sandbox config

## ContainerManager
- Extracted from MCPSandboxAdapter for testability
- Docker SDK operations: create_container, start, stop, remove, inspect
- Handles port mapping, volume mounts, environment variables
- Cleanup: removes containers by label on shutdown

## Health Monitoring
- Both adapters implement health check via WebSocket ping
- MCPSandboxAdapter: Docker container health + MCP WebSocket health
- LocalSandboxAdapter: tunnel connectivity + heartbeat response
- Unhealthy sandbox transitions to ERROR state after configurable retries

## Gotchas
- `mcp_sandbox_adapter.py` is 3069 lines -- major refactoring candidate
- Container port conflicts possible if ports 18765/16080/17681 are in use on host
- Docker socket must be accessible (`/var/run/docker.sock`)
- LocalSandboxAdapter requires user to install and run ngrok/cloudflare tunnel
- State machine transitions are NOT persisted -- container restart loses state
- Sandbox cleanup on app shutdown may leave orphaned containers if process killed (SIGKILL)
