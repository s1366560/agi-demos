# web/src/

Frontend source root. Current stack: React 19.2 + TypeScript 5.9 + Vite 7.3 +
Ant Design 6.1 + Zustand 5 + TanStack Query 5.

Last checked against code: 2026-05-18.

## Entry Points

| File | Purpose |
|---|---|
| `main.tsx` | React root, `QueryClientProvider`, `BrowserRouter`, app bootstrap. |
| `App.tsx` | Lazy-loaded route tree and auth/tenant guards. |
| `App.css`, `index.css` | Global styles and Tailwind entry. |

## Directory Map

| Directory | Purpose | Local guidance |
|---|---|---|
| `components/` | Product UI components. `agent/` is the largest subtree. | `components/agent/AGENTS.md` |
| `pages/` | Route-level pages, mostly tenant and project views. | - |
| `layouts/` | `TenantLayout`, deprecated `ProjectLayout`, `SchemaLayout`, `AgentLayout`. | - |
| `services/` | REST, WebSocket, event, sandbox, MCP, and artifact clients. | `services/AGENTS.md` |
| `stores/` | Zustand stores and agent submodules. | `stores/AGENTS.md` |
| `hooks/` | Shared React hooks. | - |
| `utils/` | Event adapters, projections, token/date/sanitize helpers. | - |
| `theme/` | Ant Design/theme provider setup. | - |
| `i18n`, `locales/` | i18next configuration and translation files. | - |
| `types/` | Shared TypeScript types. | - |
| `test/` | Vitest test helpers and test files. | - |

## Routing Facts

- All major route components are lazy-loaded in `App.tsx`.
- Current app shell is tenant-first. `TenantLayout` owns the main sidebar/header/chat shell.
- `ProjectLayout` is deprecated and kept for compatibility; project pages are routed through
  tenant-scoped routes.
- Canonical agent workspace path:
  `/tenant/:tenantId/agent-workspace/:conversation?`
- Project pages:
  `/tenant/:tenantId/project/:projectId/*`
- Top-level `/project/:projectId/*` is a legacy redirect.

## App Bootstrap

```text
ReactDOM.createRoot
  -> StrictMode
  -> QueryClientProvider
  -> BrowserRouter
  -> AppInitializer
  -> App
```

`App` wraps routes with `ErrorBoundary`, `ThemeProvider`, and `Suspense`. i18n is initialized
by importing `./i18n/config`.

## Key Rules

- Use `useShallow` for Zustand object selectors.
- Service paths are relative to `httpClient` base URL `/api/v1`.
- Agent live chat uses `agentService.ts` and `WS /api/v1/agent/ws`.
- Keep tenant/project IDs in URL/store state aligned when adding pages.
