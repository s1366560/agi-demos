# web/src/stores/

Shared Web state lives here. Business-owned stores are imported through `@business/<package>/ui/web/stores`.

## Store Inventory

| Store | File | Purpose |
|---|---|---|
| Agent main | `@business/agent/ui/web/stores/agentV3.ts` | Conversation state façade and actions; now much smaller than older docs claimed. |
| Agent modules | `@business/agent/ui/web/stores/agent/` | Conversation loading, streaming, message actions, HITL, canvas replay, tab sync, selectors. |
| Auth | `auth.ts` | Login/logout/token/user state, persisted. |
| Tenant/project | `tenant.ts`, `project.ts` | Active tenant/project context and lists. |
| Sandbox | `sandbox.ts` | Sandbox lifecycle, service status, artifact events. |
| Memory/graph | `@business/knowledge/ui/web/stores/{memory,graphStore}.ts` | Memory and graph view state. |
| Skills/agents | `@business/agent/ui/web/stores/{skill,subagent,agentDefinitions,agentBindings}.ts` | Agent configuration surfaces. |
| MCP | `mcp.ts`, `mcpAppStore.ts` | MCP server/app state. |
| HITL | `hitlStore.unified.ts` | Human-in-the-loop request state. |
| Workspace | `workspace.ts`, `canvasStore.ts`, `planReviewStore.ts`, `pendingPromptStore.ts` | Workspace, canvas, plan review, pending prompt state. |
| Ops/product | `audit.ts`, `trust.ts`, `deploy.ts`, `pool.ts`, `notification.ts`, `smtp.ts` | Admin and operational views. |

## Agent Submodules

`@business/agent/ui/web/stores/agent/` contains split-out pieces for agent state and actions, including
conversation loading, message loading, stream event handlers, selectors, HITL actions,
streaming state, tab sync, canvas replay, and plan/execution helpers.

## Critical `useShallow` Rule

Object selectors must use `useShallow`:

```ts
import { useShallow } from 'zustand/react/shallow';

const { a, b } = useStore(useShallow((state) => ({ a: state.a, b: state.b })));
const a = useStore((state) => state.a);
```

Returning a new object without `useShallow` can create infinite rerender loops.

## Store Rules

- Mutate through `set`, never by mutating state objects in place.
- Keep network calls in services and orchestration actions, not render components.
- Keep selectors stable and narrow.
- Prefer direct imports over broad store barrels.
