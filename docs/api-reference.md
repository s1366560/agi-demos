# API Reference Overview

This is a maintained route overview for the current FastAPI app. It is not a full schema
dump. Use the runtime OpenAPI schema for request/response details:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

Last checked against code: 2026-05-18.

## Runtime Registration

Routes are registered in `src/infrastructure/adapters/primary/web/main.py`. Most routers
carry their own `/api/v1` prefix; a few are included with `prefix="/api/v1"` at registration
time.

## Health

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Returns `{ "status": "ok", "version": "0.2.0" }`. |

## Authentication

| Area | Paths |
|---|---|
| Login and user | `/api/v1/auth/token`, `/api/v1/auth/me`, `/api/v1/users/me` |
| API keys | `/api/v1/auth/keys`, `/api/v1/auth/keys/{key_id}` |
| Device code | `/api/v1/auth/device/code`, `/api/v1/auth/device/approve`, `/api/v1/auth/device/token` |
| Password flow | `/api/v1/auth/force-change-password` |

API keys use the `ms_sk_` prefix and are sent with `Authorization: Bearer <key>`.

## Tenants And Projects

| Area | Paths |
|---|---|
| Tenants | `/api/v1/tenants/*` |
| Projects | `/api/v1/projects/`, `/api/v1/projects/{project_id}` |
| Project members | `/api/v1/projects/{project_id}/members/*` |
| Project stats | `/api/v1/projects/{project_id}/stats`, `/trending`, `/recent-skills` |

## Agent

| Area | Paths |
|---|---|
| Live WebSocket | `WS /api/v1/agent/ws` |
| Conversations | `/api/v1/agent/conversations`, `/api/v1/agent/conversations/{conversation_id}` |
| Messages and replay | `/api/v1/agent/conversations/{conversation_id}/messages`, `/events`, `/execution`, `/status` |
| HITL | `/api/v1/agent/hitl/conversations/{conversation_id}/pending`, `/respond`, `/cancel` |
| Tools | `/api/v1/agent/tools`, `/tools/capabilities`, `/tools/compositions` |
| Plan mode | `/api/v1/agent/plan/*` |
| Subagents | `/api/v1/agent/subagents/*` plus top-level `/api/v1/subagents/*` |
| Agent definitions and bindings | `/api/v1/agent/definitions/*`, `/api/v1/agent/bindings/*` |
| Trace | `/api/v1/agent/trace/*` |

Current live chat is WebSocket-based. Historical `POST /api/v1/agent/chat` examples are not
registered by the current router set.

## Memory, Episodes, Graph

| Area | Paths |
|---|---|
| Memories | `/api/v1/memories/`, `/api/v1/memories/{memory_id}`, `/reprocess`, `/extract-entities`, `/extract-relationships` |
| Episodes | `/api/v1/episodes/`, `/api/v1/episodes/by-name/{episode_name}`, `/api/v1/episodes/health` |
| Search | `/api/v1/memory/search`, `/api/v1/search-enhanced/*` |
| Graph | `/api/v1/graph/*` |
| Schema | `/api/v1/projects/{project_id}/schema/entities`, `/edges`, `/mappings` |
| Recall/reflection | `/api/v1/recall/*`, `/api/v1/reflection/*` |

## Workspace

| Area | Paths |
|---|---|
| Workspaces | `/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/*` |
| Workspace plan | `/api/v1/workspaces/{workspace_id}/plan/*` |
| Workspace tasks | `/api/v1/workspace-tasks/*`, `/api/v1/workspaces/{workspace_id}/autonomy/*` |
| Workspace chat/events | `/api/v1/workspace-chat/*`, `/api/v1/workspace-events/*` |
| Blackboard | `/api/v1/blackboard/*` |
| Topology | `/api/v1/topology/*` |

## Sandbox, MCP, Terminal

| Area | Paths |
|---|---|
| Sandbox lifecycle/tools | `/api/v1/sandbox/*` |
| Project sandbox | `/api/v1/projects/sandboxes/*` and project-scoped sandbox helpers |
| Terminal | `/api/v1/terminal/*` |
| MCP servers/apps/tools | `/api/v1/mcp/*` |
| Tunnel and engines | `/api/v1/tunnel/*`, `/api/v1/engines/*` |

## Product And Admin Areas

| Area | Paths |
|---|---|
| Skills | `/api/v1/skills/*`, `/api/v1/curated-skills/*`, `/api/v1/tenant-skill-configs/*` |
| Channels and webhooks | `/api/v1/channels/*`, `/api/v1/webhooks/*`, `/api/v1/tenant-webhooks/*` |
| Instances/deploy/gene market | `/api/v1/instances/*`, `/api/v1/deploys/*`, `/api/v1/genes/*`, `/api/v1/instance-templates/*` |
| Audit/trust | `/api/v1/audit/*`, `/api/v1/trust/*` |
| Observability/admin | `/api/v1/observability/*`, `/api/v1/admin/dlq/*`, `/api/v1/system/*` |
| Support/billing/notifications | `/api/v1/support/*`, `/api/v1/billing/*`, `/api/v1/notifications/*` |

## Frontend Client Conventions

The web client creates an Axios instance with `baseURL: "/api/v1"` in
`web/src/services/client/httpClient.ts`. Frontend service paths should therefore be relative
to `/api/v1`, for example `/mcp/apps` rather than `/api/v1/mcp/apps`.

For FastAPI collection endpoints with trailing slash definitions, keep the trailing slash in
frontend calls to avoid cross-origin 307 redirects in Vite development.
