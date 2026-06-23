# MemStack Architecture

Last checked against code: 2026-06-23.

MemStack is organized around DDD and hexagonal architecture, with a separate React web
console and an agent runtime that uses Ray actors, Redis streams, MCP tools, and WebSocket
delivery.

## High-Level Runtime

```text
React Web Console
  | HTTP API + WebSocket
FastAPI primary adapters
  | application services / use cases
Domain model + ports
  | repository/service interfaces
Secondary adapters
  | PostgreSQL, Redis, Neo4j, MinIO, Docker/Ray, MCP, LLM providers
Agent runtime
  | ReAct processor, tools, HITL, subagents, workspace orchestration
```

## Backend Layers

| Layer | Path | Responsibility |
|---|---|---|
| Domain | `src/domain` | Business entities, value objects, domain events, repository/service ports. |
| Application | `src/application` | Use cases, application services, schemas, orchestration flows. |
| Primary adapters | `src/infrastructure/adapters/primary/web` | FastAPI routers, WebSocket router, request middleware, startup wiring. |
| Secondary adapters | `src/infrastructure/adapters/secondary` | Persistence, sandbox, messaging, channel and external service adapters. |
| Configuration | `src/configuration` | Settings, dependency injection, bounded containers. |

## Domain Areas

The current domain model includes:

- Agent: conversations, messages, execution records, tool policy, agent definitions,
  bindings, subagents, HITL, tasks, prompts, workspace config.
- Memory: memories, episodes, entities, communities.
- Tenant/project/auth: users, roles, API keys, tenants, projects, invitations.
- Sandbox/MCP: project sandboxes, MCP apps, MCP servers, tools, transport.
- Workspace: workspaces, members, workspace agents, tasks, topology, blackboard, WTP
  envelopes, workspace plans.
- Operations: audit logs, trust policy, decision records, SMTP, cron, deploy records,
  observability/dead-letter state.
- Instance/gene system: instances, instance templates, genes, genomes, gene market,
  evolution events.

## API Layer

`src/infrastructure/adapters/primary/web/main.py` creates the FastAPI app, configures
logging redaction, CORS, gettext locale middleware, rate limiting, exception handlers,
startup/shutdown hooks, `/health`, static files, and routers.

Major router groups:

- Auth, tenants, projects, invitations.
- Agent metadata, conversations, WebSocket, HITL, trace, tools, subagents, definitions,
  bindings, plan mode.
- Memories, episodes, graph, schema, recall, reflection, enhanced search.
- Workspace, workspace plans/tasks/autonomy/events/chat, blackboard, topology.
- Sandbox, project sandbox, terminal, MCP.
- Skills, channels, webhooks, instances, deploy, genes, audit, trust,
  agent pool admin, observability and admin DLQ.

See [../api-reference.md](../api-reference.md) for route families.

## Agent Runtime

Important paths:

| Area | Path |
|---|---|
| ReAct core | `src/infrastructure/agent/core` |
| Session processor | `src/infrastructure/agent/processor` |
| Tools | `src/infrastructure/agent/tools` |
| Tool wrapping/conversion | `src/infrastructure/agent/core/tool_converter.py` |
| HITL | `src/infrastructure/agent/hitl`, `src/infrastructure/agent/actor/hitl_router_actor.py` |
| Ray actor runtime | `src/infrastructure/agent/actor` |
| Subagents | `src/infrastructure/agent/subagent` |
| Routing | `src/infrastructure/agent/routing` |
| Events | `src/domain/events`, `src/infrastructure/agent/events` |
| Workspace orchestration | `src/infrastructure/agent/workspace`, `src/infrastructure/agent/workspace_plan` |

Plan-related HTTP APIs are split by scope: conversation mode/task-list endpoints live under
`/api/v1/agent/plan/*`, while durable workspace planning lives under
`/api/v1/workspaces/{workspace_id}/plan/*`.

Execution flow in broad terms:

1. The web console connects to `WS /api/v1/agent/ws`.
2. `SendMessageHandler` validates and hands chat work to the agent service/runtime.
3. The runtime uses the session processor and ReAct core to produce thought/tool/text events.
4. Tool calls execute through built-in `@tool_define` tools, plugin tools, MCP tools, or
   sandbox wrappers.
5. Domain events are converted to streamable event dictionaries and delivered through
   WebSocket/Redis/PostgreSQL paths.
6. HITL requests pause execution with persisted state and resume through HITL response routes
   or WebSocket messages.

## Event Flow

`src/domain/events/types.py` is the source of truth for event names. Event objects live in
`src/domain/events/agent_events.py`; conversion and delivery live under
`src/infrastructure/agent/events` and the web adapter layer.

Frontend event adaptation is centered around:

- `web/src/services/agentService.ts`
- `web/src/services/agent/messageRouter.ts`
- `web/src/utils/sseEventAdapter.ts`
- `web/src/stores/agent/*`
- `web/src/stores/sandbox.ts`

## Data Stores

| Store | Role |
|---|---|
| PostgreSQL | Tenants, users, projects, conversations, messages, execution records, skills, MCP records, sandbox records, workspace/plan state, audit/trust/admin data. |
| Redis | Agent event streams, runtime state, queues, outbox support, cache/state coordination. |
| Neo4j | Native graph adapter storage for memory/entity/community graph operations. |
| MinIO | Object storage for artifacts and larger file payloads. |

Database models are centralized in
`src/infrastructure/adapters/secondary/persistence/models.py`; migrations are managed with
Alembic.

## Web Console

Important paths:

| Area | Path |
|---|---|
| App routes | `web/src/App.tsx` |
| Layouts | `web/src/layouts` |
| Agent UI | `web/src/components/agent` |
| Workspace UI | `web/src/components/workspace`, `web/src/pages/tenant/Workspace*` |
| Services | `web/src/services` |
| HTTP client | `web/src/services/client/httpClient.ts` |
| Stores | `web/src/stores` |
| Theme/i18n | `web/src/theme`, `web/src/i18n`, `web/src/locales` |

The HTTP client uses `baseURL: "/api/v1"`. WebSocket chat and subscriptions are handled by
`web/src/services/agentService.ts`.

## Sandbox And MCP

The backend exposes sandbox lifecycle and tool routes under `/api/v1/sandbox/*` plus
project-sandbox routes. The agent runtime can wrap sandbox MCP tools and uses
`MCPSandboxAdapter`/`LocalSandboxAdapter` behind service boundaries.

The sandbox server lives in `sandbox-mcp-server/` and provides file, shell, artifact,
terminal, desktop, browser, code-intel, and testing capabilities to agents through MCP.

## Startup And Background Workers

FastAPI startup initializes:

- telemetry and logging redaction,
- database schema/default credentials,
- LLM providers and health checker,
- graph service,
- workflow engine,
- Redis and DI container,
- Docker/sandbox services,
- workspace supervisor and outbox workers,
- task execution session recovery,
- channel manager and background task cleanup.

Ray actor and worker behavior is controlled through Makefile targets and Docker Compose files.

## Constraints To Preserve

- Use `DIContainer.with_db(db)` or scoped construction for DB-backed services; the global
  app container is for singleton dependencies.
- Do not bypass Alembic for schema changes.
- Keep tenant/project scoping on data access.
- Keep frontend service paths relative to `/api/v1`.
- Keep WebSocket chat docs separate from historical REST/SSE chat docs.
