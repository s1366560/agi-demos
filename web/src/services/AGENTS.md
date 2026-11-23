# web/src/services/

Shared HTTP and WebSocket transports live here. Each business package owns its operation-specific clients in `plugins/business/<package>/ui/web/services`.

## HTTP Client

| File                                                           | Purpose                                                                   |
| -------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `client/httpClient.ts`                                         | Axios instance, `baseURL = "/api/v1"`, auth and locale interceptors.      |
| `client/ApiError.ts`                                           | Typed API error parsing.                                                  |
| `client/urlUtils.ts`                                           | HTTP/WS URL helpers.                                                      |
| `client/queryClient.ts`                                        | TanStack Query client setup.                                              |
| `client/requestCache.ts`, `requestDeduplicator.ts`, `retry.ts` | Legacy helpers; HTTP-layer dedupe/retry is not active in `httpClient.ts`. |

## Path Convention

`httpClient` already prefixes `/api/v1`.

```ts
httpClient.get('/mcp/apps'); // correct
httpClient.get('/api/v1/mcp/apps'); // wrong
```

Preserve trailing slashes for collection endpoints that FastAPI defines with trailing slashes.

## Key Services

| Service                                                                 | Purpose                                                           | Transport        |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------- | ---------------- |
| `agentService.ts`                                                       | Agent WebSocket connection, conversation metadata, event routing. | WebSocket + REST |
| `projectService.ts`, `tenantService` equivalents                        | Project/tenant CRUD and stats.                                    | REST             |
| `@business/knowledge/ui/web/services/{memoryService,graphService,knowledgeApi}.ts`              | Memory, communities, graph/search APIs.                           | REST             |
| `sandboxService.ts`, `projectSandboxService.ts`, `sandboxSSEService.ts` | Sandbox lifecycle, project sandbox, service events.               | REST + SSE/WS    |
| `mcpService.ts`, `mcpAppService.ts`                                     | MCP servers, tools, apps.                                         | REST             |
| `hitlService.unified.ts`                                                | HITL pending/respond/cancel REST paths.                           | REST             |
| `artifactService.ts`, `instanceFileService.ts`                          | Artifacts and files.                                              | REST             |
| `workspaceService.ts`, `workspaceTaskProjection.ts` utilities           | Workspace/workspace-task data flows.                              | REST/events      |
| `unifiedEventService.ts`, `eventQueue.ts`                               | Project/domain event subscriptions and ordered handling.          | WebSocket/REST   |

## Agent Event Flow

```text
WS /api/v1/agent/ws
  -> agentService.ts
  -> services/agent/messageRouter.ts
  -> utils/sseEventAdapter.ts (normalization)
  -> @business/agent/ui/web/stores/{agent/*,agentV3.ts}
  -> components/agent/*
```

The `sseEventAdapter` name is historical; the live transport is WebSocket.

## Rules

- Do not create a separate Axios client unless there is a clear transport boundary.
- Do not manually attach auth tokens outside `httpClient` unless using WebSocket
  subprotocol/query auth.
- Keep service methods thin; put UI state in stores/hooks.
- For new WebSocket message types, update both backend handlers and frontend
  `services/agent/messageRouter.ts`.
