# MemStack Web Console

The web console is a React 19 + TypeScript application for operating MemStack tenants,
projects, agents, workspaces, memory graphs, MCP integrations, sandboxes, and admin views.

Last checked against code: 2026-05-18.

Additional web docs start at [web/docs/README.md](docs/README.md).

## Stack

| Area | Current implementation |
|---|---|
| Framework | React 19.2, React Router 7 |
| Build | Vite 7.3, TypeScript 5.9 |
| UI | Ant Design 6.1, lucide-react, custom shared UI components |
| State/data | Zustand 5, TanStack Query 5, SWR |
| Realtime | Agent WebSocket service, sandbox SSE/WebSocket adapters, event bus client |
| Visualization | Cytoscape, Chart.js, Mermaid, KaTeX, Three.js/react-three-fiber |
| Tests | Vitest, Testing Library, Playwright |

Vite 7 requires Node `^20.19.0 || >=22.12.0`. Dependencies are managed with pnpm; the
package declares `pnpm@10.24.0`.

## Commands

```bash
cd web
pnpm install
pnpm run dev
pnpm run type-check
pnpm run test
pnpm run build
pnpm run test:e2e
```

From the repository root:

```bash
make dev-web       # foreground web server on :3000
make dev           # full stack, including web in background
```

## Development Server

The Vite dev server runs on `http://localhost:3000` with `strictPort: true`.

`web/vite.config.ts` proxies `/api` to `http://localhost:8000`, so browser requests can use
relative `/api/v1/...` paths during local development.

## API Client Rules

`web/src/services/client/httpClient.ts` sets:

```ts
export const API_BASE_URL = '/api/v1';
```

Service modules should pass paths relative to `/api/v1`:

```ts
httpClient.get('/mcp/apps');      // correct
httpClient.get('/api/v1/mcp/apps'); // wrong: doubles the prefix
```

For collection endpoints defined with a trailing slash in FastAPI, keep the trailing slash in
frontend calls to avoid 307 redirects that can strip `Authorization` in Vite development.

## Current App Structure

```text
web/src/
  App.tsx                         Route tree and lazy-loaded pages
  layouts/                        Tenant, project, schema, agent layouts
  pages/
    tenant/                       Tenant-level product pages
    project/                      Project memory/graph/schema/support pages
    admin/                        Admin dashboards
  components/
    agent/                        Agent workspace, chat, timeline, HITL, sandbox, canvas
    workspace/                    Workspace UI and collaboration components
    graph/                        Graph visualization
    mcp, mcp-app, skill, provider  Integration and configuration surfaces
    shared, ui, common            Shared primitives
  services/                       HTTP clients, WebSocket clients, event routing
  stores/                         Zustand stores
  hooks/                          Shared React hooks
  utils/                          Event adapters, projections, sanitizers, exports
  theme/                          AntD theme and app theme provider
  i18n, locales/                  i18next configuration and translations
  test/                           Unit/component test support
```

## Major Routes

Routes are defined in `web/src/App.tsx` and are lazy-loaded. Key areas:

| Area | Examples |
|---|---|
| Auth | `/login`, `/login/callback/:provider`, `/invite/:token`, `/device`, `/force-change-password` |
| Tenant | `/tenant/:tenantId/overview`, `/projects`, `/users`, `/providers`, `/settings` |
| Agent | `/tenant/:tenantId/agent-workspace/:conversation?`, `/agents`, `/subagents`, `/agent-definitions`, `/agent-bindings` |
| Skills/plugins | `/skills`, `/templates`, `/plugins`, `/mcp-servers`, `/runtimes` |
| Workspace | `/workspaces`, `/workspaces/new`, project-scoped workspace routes |
| Instances/genes | `/instances`, `/instances/:instanceId`, `/deploy`, `/genes`, `/instance-templates` |
| Project | `/tenant/:tenantId/project/:projectId/memories`, `/graph`, `/entities`, `/communities`, `/schema/*`, `/blackboard`, `/playbooks` |
| Admin/ops | `/pool`, `/audit-logs`, `/trust-policies`, `/decision-records`, `/org-settings/*` |

## Realtime Agent Flow

The current live agent transport is WebSocket-based:

- Backend endpoint: `WS /api/v1/agent/ws`
- Frontend service: `web/src/services/agentService.ts`
- Message routing: `web/src/services/agent/messageRouter.ts`
- Event adaptation: `web/src/utils/sseEventAdapter.ts`
- Agent state stores: `web/src/stores/agent*`, `web/src/stores/agent/*`

The frontend still has adapters named after SSE because they normalize historical event
shapes, but live chat is handled by the WebSocket service.

## Testing

```bash
pnpm run type-check
pnpm run test
pnpm run test:e2e
pnpm run build
```

Use focused tests during iteration:

```bash
pnpm run test -- src/test/services/agentService.subagent-events.test.ts
pnpm run test -- src/test/components/agent/MessageArea.test.tsx
pnpm run test:e2e -- e2e/agent.spec.ts
```

## Troubleshooting

| Symptom | Check |
|---|---|
| 401 after a collection request | Confirm the frontend service path keeps the trailing slash expected by FastAPI. |
| Request path is `/api/v1/api/v1/...` | Remove the duplicate `/api/v1` from the service module. |
| Infinite rerender with Zustand | Use `useShallow` for object selectors. |
| WebSocket connects but no events arrive | Check `agentService.ts` subscription state and backend `/api/v1/agent/ws` logs. |
| Port 3000 in use | Run `make dev-web-stop` or stop the process using the port. |
