# web/src/services/

API service layer. 37 service files + `client/` (HTTP infra) + `mcp/` (MCP protocol).

## HTTP Client (client/)

| File | Purpose |
|------|---------|
| `httpClient.ts` | Axios instance. **baseURL = `/api/v1`**. Auth token injected via interceptor |
| `ApiError.ts` | Error parsing from Axios responses |
| `urlUtils.ts` | `createWebSocketUrl()` -- converts HTTP URL to WS URL |
| `requestCache.ts` | Request caching (deprecated, currently unused) |
| `requestDeduplicator.ts` | Request deduplication (deprecated) |
| `retry.ts` | Retry logic (deprecated) |

## CRITICAL: Path Convention

- `httpClient` baseURL is `/api/v1` -- all service paths are RELATIVE to that
- `'/mcp/apps'` resolves to `/api/v1/mcp/apps` (correct)
- `'/api/v1/mcp/apps'` resolves to `/api/v1/api/v1/mcp/apps` (WRONG -- doubled prefix)

## Key Services

| Service | Purpose | Transport |
|---------|---------|-----------|
| `agentService.ts` | Agent chat, conversations, streaming (2600+ lines) | WebSocket + REST |
| `projectService.ts` | Project CRUD | REST |
| `memoryService.ts` | Memory CRUD + search | REST |
| `skillService.ts` | Skill management | REST |
| `subagentService.ts` | SubAgent management | REST |
| `sandboxService.ts` | Sandbox lifecycle | REST |
| `sandboxSSEService.ts` | Sandbox terminal/desktop streaming | SSE |
| `mcpService.ts` / `mcpAppService.ts` | MCP server/tool management | REST |
| `graphService.ts` | Knowledge graph queries | REST |
| `hitlService.unified.ts` | HITL request/response | REST |
| `artifactService.ts` | Artifact upload/download | REST |
| `channelService.ts` | Channel plugin management | REST |
| `billingService.ts` | Billing/usage data | REST |

## agentService.ts (2600+ lines)

- Implements `AgentService` interface with full type-safe event handling
- `chat()` -- sends message, returns WebSocket-based streaming handler
- `createConversation()`, `getConversation()`, `listConversations()` -- REST calls
- `connectWebSocket()` -- establishes WS connection to `/ws/agent/{conversationId}`
- 40+ event data types imported from `types/agent.ts`
- `routeToHandler()` dispatches SSE events to typed handler callbacks

## SSE/WebSocket Event Flow

```
Backend SSE -> WebSocket -> agentService.routeToHandler() -> AgentStreamHandler callbacks
  -> stores/agent/streamEventHandlers.ts -> Zustand state update -> UI re-render
```

## Service Pattern

```typescript
const BASE_URL = '/some-resource';  // relative to /api/v1
export const someService = {
  list: (params) => httpClient.get(BASE_URL, { params }),
  getById: (id) => httpClient.get(`${BASE_URL}/${id}`),
  create: (data) => httpClient.post(BASE_URL, data),
};
```

## mcp/ Subdirectory

- MCP-specific service helpers for MCP server management

## Forbidden

- Never use absolute paths like `/api/v1/...` in service URLs
- Never create new Axios instances -- use `httpClient` from `client/httpClient.ts`
- Never handle auth tokens manually -- interceptor does it
