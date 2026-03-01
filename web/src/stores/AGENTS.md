# web/src/stores/

Zustand state stores. 22 files + `agent/` subdir (6 files).

## Store Inventory

| Store | File | Purpose |
|-------|------|---------|
| Agent (main) | `agentV3.ts` | Conversation state, messages, streaming (1950+ lines) |
| Agent sub-modules | `agent/` | Split-out logic from agentV3 |
| Auth | `auth.ts` | Login/logout, token, user. Uses `persist` middleware |
| Project | `project.ts` | Active project state |
| Tenant | `tenant.ts` | Active tenant state |
| Sandbox | `sandbox.ts` | Sandbox instance state |
| Memory | `memory.ts` | Memory list/search state |
| Skill | `skill.ts` | Skill list state |
| SubAgent | `subagent.ts` | SubAgent list state |
| MCP | `mcp.ts` | MCP server state |
| MCP App | `mcpAppStore.ts` | MCP app marketplace state |
| HITL | `hitlStore.unified.ts` | Human-in-the-loop request state |
| Canvas | `canvasStore.ts` | Artifact canvas panel state |
| Background | `backgroundStore.ts` | Background SubAgent panel state |
| Context | `contextStore.ts` | Context window management state |
| Layout Mode | `layoutMode.ts` | Chat layout mode (chat/task/code/canvas) |
| Pool | `pool.ts` | Agent pool dashboard state |
| Channel | `channel.ts` | Channel plugin state |
| Theme | `theme.ts` | Dark/light theme preference |
| Notification | `notification.ts` | Notification state |
| Template | `templateStore.ts` | Template marketplace state |
| Conv Labels | `conversationLabelsStore.ts` | Conversation label/tag state |

## agent/ Subdir (decomposed from agentV3.ts)

| File | Purpose |
|------|---------|
| `streamEventHandlers.ts` | SSE event handler factory (1500+ lines). Creates `AgentStreamHandler` |
| `hitlActions.ts` | HITL action creators (clarification, decision, env_var, permission) |
| `conversationsStore.ts` | Conversation list management |
| `executionStore.ts` | Execution details state |
| `streamingStore.ts` | Streaming connection state |
| `timelineStore.ts` | Timeline event state |

## agentV3.ts Architecture

- `create<AgentV3State>()(devtools(persist(...)))` -- both devtools + persist middleware
- Per-conversation state via `Map<string, ConversationState>`
- Delta buffers batch rapid token updates every 50ms to reduce re-renders
- `MAX_CACHED_CONVERSATIONS = 10` -- LRU eviction for inactive conversations
- Persists to IndexedDB via `conversationDB.ts` utils

## CRITICAL: useShallow Rule

- Object selectors MUST use `useShallow` from `'zustand/react/shallow'` (see root AGENTS.md for full examples)
- Single-value selectors are safe without useShallow
- Violating this causes infinite re-render loops

## Store Creation Pattern

- `create<State>()(devtools((set, get) => ({ ... }), { name: 'store-name' }))` -- standard pattern
- Most stores use `devtools()` (visible in Redux DevTools)
- `auth.ts` adds `persist()` for localStorage; `agentV3.ts` uses both `devtools()` + `persist()`

## Exported Selector Hooks Pattern

```typescript
export const useItems = () => useExampleStore((state) => state.items);  // single value
export const useExampleActions = () =>                                   // multi-value
  useExampleStore(useShallow((state) => ({ fetch: state.fetch, reset: state.reset })));
```

## Forbidden

- Never return object from Zustand selector without `useShallow`
- Never mutate state directly -- always use `set()` from store
- Never import from store barrel files -- use direct imports
