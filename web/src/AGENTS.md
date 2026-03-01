# web/src/

Frontend root. React 19.2 + TypeScript 5.9 + Vite 7.3 + Ant Design 6.1 + Zustand 5.0.

## Entry Points

| File | Purpose |
|------|---------|
| `main.tsx` | ReactDOM.createRoot, BrowserRouter, AppInitializer wrapper |
| `App.tsx` | Route definitions (~700 lines). All routes lazy-loaded via `React.lazy()` |
| `App.css` / `index.css` | Global styles |

## Directory Map

| Dir | Purpose | Child AGENTS.md |
|-----|---------|-----------------|
| `components/` | Reusable UI components. `agent/` is the largest (57 entries) | `components/agent/AGENTS.md` |
| `pages/` | Route-level page components (25+ pages, mostly under `tenant/`) | -- |
| `stores/` | Zustand state stores (22 files + `agent/` subdir) | `stores/AGENTS.md` |
| `services/` | API service clients (37 files + `client/`, `mcp/` subdirs) | `services/AGENTS.md` |
| `hooks/` | Custom React hooks (sandbox detection, debounce, etc.) | -- |
| `types/` | TypeScript type definitions (agent, memory, common, etc.) | -- |
| `i18n/` | i18n config (i18next). `locales/` has en/zh JSON files | -- |
| `layouts/` | Layout shells: `TenantLayout`, `ProjectLayout`, `SchemaLayout` | -- |
| `theme/` | ThemeProvider (Ant Design 6 token customization) | -- |
| `config/` | `navigation.ts` -- sidebar nav item definitions | -- |
| `utils/` | Utility functions (export, logger, tabSync, tokenResolver) | -- |
| `styles/` | Shared CSS/style modules | -- |
| `vendor/` | Vendored third-party code | -- |
| `constants/` | App-wide constants | -- |
| `test/` | Frontend test setup (Vitest) | -- |

## Routing (App.tsx)

- All route components are `lazy(() => import(...))` with `<Suspense>` fallback
- Layout hierarchy: `TenantLayout` > `ProjectLayout` > page component
- Key routes: `/login`, `/tenant/:tenantId/*`, `/tenant/:tenantId/project/:projectId/*`
- Agent workspace: `/tenant/:tenantId/agent` (most complex page)

## App Bootstrap (main.tsx)

```
ReactDOM.createRoot -> StrictMode -> BrowserRouter -> AppInitializer -> App
```

- `AppInitializer` handles auth check, tenant loading on mount
- `ThemeProvider` wraps inside App.tsx (Ant Design ConfigProvider + theme tokens)
- i18n initialized via `import './i18n/config'` side effect in App.tsx

## Key Patterns

- Lazy loading for ALL route components (code splitting)
- `ErrorBoundary` wraps routes for crash resilience
- Auth guard: checks `useAuthStore` for `isAuthenticated`, redirects to `/login`
- Multi-tenant: `tenantId` from URL params, stored in `useTenantStore`
- Project scoping: `projectId` from URL params, stored in `useProjectStore`
