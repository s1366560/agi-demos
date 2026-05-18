# Frontend Codemap

Last updated: 2026-05-18.

## Stack

| Area | Current implementation |
|---|---|
| Framework | React 19.2.3 |
| Language | TypeScript 5.9.3 |
| Build | Vite 7.3.0 |
| Routing | React Router 7.11.0 |
| UI | Ant Design 6.1.1, Tailwind CSS 4.1.18, lucide-react |
| State/data | Zustand 5.0.9, TanStack Query 5.99.2, SWR |
| Realtime | WebSocket agent service, sandbox SSE/WebSocket helpers |
| Tests | Vitest 4, Playwright 1.57 |

## Bootstrap

```text
src/main.tsx
  -> StrictMode
  -> QueryClientProvider
  -> BrowserRouter
  -> AppInitializer
  -> App
```

`App` sets up `ErrorBoundary`, `ThemeProvider`, lazy routes, auth redirects, tenant/project
context sync, and `Suspense` fallback handling.

## Directory Map

```text
web/src/
  App.tsx                         Route tree
  main.tsx                        App bootstrap
  layouts/                        Tenant, schema, agent, deprecated project layout
  pages/
    tenant/                       Tenant-level product pages and AgentWorkspace
    project/                      Tenant-scoped project pages
    admin/                        Admin dashboards
  components/
    agent/                        Agent chat/timeline/HITL/canvas/sandbox UI
    workspace/                    Workspace and objective UI
    graph/                        Cytoscape graph visualization
    mcp, mcp-app, skill, provider Integration/configuration surfaces
    shared, ui, common            Shared UI primitives
  services/                       HTTP, WebSocket, event, sandbox, MCP clients
  stores/                         Zustand stores
  hooks/                          Shared hooks
  utils/                          Event adapters, projections, helpers
  theme/                          Theme provider and AntD tokens
  i18n, locales/                  i18next config and translations
  test/                           Vitest tests and fixtures
```

## Routes

Canonical routes are defined in `src/App.tsx`.

| Area | Examples |
|---|---|
| Public/auth | `/login`, `/login/callback/:provider`, `/invite/:token`, `/device`, `/force-change-password`, `/tenants/new` |
| Tenant home | `/tenant`, `/tenant/:tenantId/overview` |
| Agent workspace | `/tenant/:tenantId/agent-workspace/:conversation?` |
| Tenant admin/product | `/projects`, `/users`, `/providers`, `/analytics`, `/events`, `/webhooks`, `/billing`, `/settings`, `/org-settings/*` |
| Skills/plugins/MCP | `/skills`, `/curated-skills`, `/templates`, `/plugins`, `/mcp-servers`, `/runtimes` |
| Workspaces | `/workspaces`, `/workspaces/new`, project-scoped workspace routes |
| Instances/deploy/genes | `/instances`, `/instances/:instanceId`, `/deploy`, `/genes`, `/instance-templates` |
| Project pages | `/tenant/:tenantId/project/:projectId/memories`, `/graph`, `/entities`, `/communities`, `/advanced-search`, `/schema/*`, `/blackboard`, `/playbooks` |
| Ops | `/pool`, `/audit-logs`, `/trust-policies`, `/decision-records` |

`/project/:projectId/*` is a legacy redirect to tenant-scoped project routes. `ProjectLayout`
is deprecated and should not be used for new pages.

## Services

| Service area | Files |
|---|---|
| HTTP client | `services/client/httpClient.ts`, `ApiError.ts`, `queryClient.ts`, `urlUtils.ts` |
| Agent | `services/agentService.ts`, `services/agent/*` |
| Memory/graph | `memoryService.ts`, `clusterService.ts`, graph/project search services |
| Sandbox | `sandboxService.ts`, `projectSandboxService.ts`, `sandboxSSEService.ts` |
| MCP/plugin | `mcpService.ts`, `mcpAppService.ts`, `services/mcp/*` |
| Events | `eventBusClient.ts`, `unifiedEventService.ts`, `eventQueue.ts` |
| Workspace/instances | `workspaceService.ts`, `instanceService` family, deploy/gene/template services |

Service paths are relative to `/api/v1` because `httpClient` sets that base URL.

## Agent Realtime Flow

```text
AgentWorkspace
  -> AgentChatContent
  -> useAgentV3Store and stores/agent/*
  -> agentService.ts
  -> WS /api/v1/agent/ws
  -> services/agent/messageRouter.ts
  -> utils/sseEventAdapter.ts
  -> timeline/HITL/canvas/sandbox components
```

The adapter name `sseEventAdapter` is historical; current live chat is WebSocket-based.

## Stores

| Store | Purpose |
|---|---|
| `auth.ts` | Auth token and current user. |
| `tenant.ts`, `project.ts` | Active tenant/project context. |
| `agentV3.ts`, `stores/agent/*` | Agent conversations, messages, streaming, HITL, timeline. |
| `sandbox.ts` | Sandbox/service/artifact event state. |
| `memory.ts`, `cluster.ts`, `graphStore.ts` | Memory and graph views. |
| `workspace.ts`, `canvasStore.ts`, `planReviewStore.ts` | Workspace, canvas, plan review state. |
| `mcp.ts`, `mcpAppStore.ts`, `skill.ts`, `subagent.ts` | Integration and agent configuration surfaces. |

Object selectors must use `useShallow`.

## Component Hotspots

| Path | Notes |
|---|---|
| `components/agent/AgentChatContent.tsx` | Main agent workspace composition. |
| `components/agent/MessageArea.tsx` | Timeline/message list container. |
| `components/agent/chat/` | Markdown, code, mermaid, search, streaming, suggestions, model controls. |
| `components/agent/timeline*` | Event-specific timeline rendering. |
| `components/agent/canvas/` | Artifact and interactive canvas surface. |
| `components/agent/sandbox/` | Terminal/desktop/sandbox status UI. |
| `layouts/TenantLayout.tsx` | Current app shell. |

## Maintenance Checklist

When changing frontend architecture:

1. Update this codemap and `web/README.md`.
2. Update local `AGENTS.md` files when route/service/store facts change.
3. Verify `pnpm run type-check` and targeted Vitest/Playwright tests.
4. Keep API paths relative to `/api/v1`.
