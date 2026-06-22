# Web Frontend Architecture Rules

These conventions are adopted from `multica`'s architecture handoff notes
and adapted for MemStack's single-frontend setup. They are **normative**
for new code; legacy code migrates gradually.

## Layering

The diagram below describes the **target** dependency direction
(`components`/`hooks` must reach `services` only through `stores` or
dedicated hooks), not the current state of the tree — see Rule 4 for
the enforcement gap.

```
components/  ──┐
               │  (must go through)
hooks/        ─┼──► stores/  ──► services/api  ──► httpClient
               │                 services/client/* (WS, singletons)
               │                 services/{feature}Service.ts
               └──► services/client/queryClient  (React Query)
```

**Rules**

1. **`services/` = IO only.** Never hold UI state. Axios wrappers, WS
   clients, adapter logic. Pure and serializable in/out.
2. **`stores/` = client state only.** UI toggles, form drafts, ephemeral
   selections. Server snapshots MUST NOT live here going forward — they
   belong in React Query cache.
3. **WS event handlers `invalidate`, not `push`.** Redis / WebSocket
   event handlers should call `queryClient.invalidateQueries(...)` (or
   `setQueryData` for surgical optimistic updates) rather than pushing
   data into Zustand stores. This keeps a single source of truth per
   server-owned entity.
4. **Components never import `services/*` directly.** Always flow
   through a hook (`hooks/queries/*` or `hooks/use*`) or store. This is
   normative for new code; legacy components are grandfathered and
   migrate gradually. **Not yet enforced** — `web/eslint.config.js`'s
   `no-restricted-imports` currently only blocks barrel imports from
   `@/components/agent` and `@/components/index`; it does not restrict
   `@/services/*`. As of this writing, ~48 component files still import
   `@/services/*` directly (~63 import lines), so treat this rule as a
   target, not a gate.
5. **Project scope is explicit.** Components and stores must derive the
   active project from tenant-prefixed route params, query params, or the
   tenant-scoped `useProjectStore.currentProject` value after checking
   `project.tenant_id`. Do not introduce hidden global project singletons
   or implicit HTTP headers for tenant/project scoping.
6. **Tenant/project request scope travels with the API call.** Service
   methods should pass `tenant_id` / `project_id` in the endpoint or query
   params required by the backend contract. Do not rely on httpClient to
   infer project scope.

## New Hooks Pattern (React Query)

```ts
// hooks/queries/useX.ts
import { useQuery } from '@tanstack/react-query';
export const xKeys = {
  all: ['x'] as const,
  list: (scope: string) => [...xKeys.all, 'list', scope] as const,
};
export function useX(scope: string | undefined) {
  return useQuery({
    queryKey: scope ? xKeys.list(scope) : xKeys.all,
    queryFn: () => xAPI.list(scope!),
    enabled: !!scope,
  });
}
```

- Defaults: `staleTime: 30s`, `refetchOnWindowFocus: true` — see
  `services/client/queryClient.ts`.
- Mutations should call `queryClient.invalidateQueries({ queryKey })`
  on success.

## Route Naming (warn-only)

New top-level routes must be single words (`/agents`) or `/{noun}/{verb}`
(`/agents/new`). Avoid hyphenated compounds (`/agent-workspace`) — they
usually mask missing noun/verb decomposition. Existing offenders are
grandfathered via `scripts/check-route-naming.mjs`'s allowlist.

## WebSocket Resilience

All app-owned WS clients (`services/agent/wsConnection.ts`,
`services/unifiedEventService.ts`) attach a **half-open watchdog** via
`services/client/wsWatchdog.ts`. If the
socket receives no inbound frames for `staleAfterMs`, it force-closes
with code `4000` so the reconnect logic runs. Browsers do not surface
TCP-level pong, so this inbound-staleness check is the only reliable
way to detect NAT silent drops and laptop-sleep half-opens.

For UI views that hold long-lived state, use
`hooks/useRevalidateOnVisibility` to revalidate on tab focus as a
backstop.

## Zustand + useShallow

Always use `useShallow` when selecting multiple values (see AGENTS.md
gotchas). Single-value selectors do not need it.

## File Size

Aim for 200–400 lines; hard cap at 800. Split by concern when exceeded.
