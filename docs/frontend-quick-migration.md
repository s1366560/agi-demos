# Frontend Sandbox Module Guide (Project-Scoped API)

> Migration status: complete. The project-scoped sandbox API is the only
> sandbox path used by `web/src/stores/sandbox.ts`; the store imports
> `projectSandboxService` exclusively and has no `sandboxService` fallback.

## Quick Start (5 minutes)

### 1. Import New Service

```typescript
import { projectSandboxService } from '../services/projectSandboxService';
```

### 2. Ensure a Sandbox

```typescript
const ensureSandbox = useCallback(async () => {
  if (activeSandboxId) return activeSandboxId;
  if (!projectId) return null;

  try {
    const sandbox = await projectSandboxService.ensureSandbox(projectId);
    setSandboxId(sandbox.sandbox_id);
    return sandbox.sandbox_id;
  } catch (error) {
    console.error('[AgentChat] Failed to ensure sandbox:', error);
    return null;
  }
}, [activeSandboxId, projectId, setSandboxId]);
```

### 3. Store Actions

The sandbox store (`stores/sandbox.ts`) uses the project-scoped API directly.
There is no v1 fallback branch; `activeProjectId` is required before calling
desktop/terminal actions.

```typescript
// In stores/sandbox.ts:
startDesktop: async (resolution = '1920x1080') => {
  const { activeProjectId } = get();

  if (!activeProjectId) {
    logger.warn('[SandboxStore] Cannot start desktop: no active project');
    return;
  }

  const status = await projectSandboxService.startDesktop(activeProjectId, resolution);
  set({ desktopStatus: status });
}
```

## API Endpoint Mapping

| Old Endpoint | New Endpoint | Method |
|--------------|--------------|--------|
| `/sandbox/create` | `/projects/{id}/sandbox` | POST |
| `/sandbox/{id}` | `/projects/{id}/sandbox` | GET |
| `/sandbox/{id}/desktop` | `/projects/{id}/sandbox/desktop` | POST |
| `/sandbox/{id}/terminal` | `/projects/{id}/sandbox/terminal` | POST |
| `/sandbox/{id}/desktop` | `/projects/{id}/sandbox/desktop` | DELETE |
| `/sandbox/{id}/terminal` | `/projects/{id}/sandbox/terminal` | DELETE |

## New Features Available

### Execute Tool Directly

```typescript
const result = await projectSandboxService.executeTool(projectId, {
  tool_name: 'bash',
  arguments: { command: 'ls -la' },
  timeout: 30
});

console.log(result.content);
```

### Health Check

```typescript
const health = await projectSandboxService.healthCheck(projectId);
console.log('Healthy:', health.healthy);
```

### Sync Status

```typescript
const sandbox = await projectSandboxService.syncSandboxStatus(projectId);
console.log('Status:', sandbox.status);
```

## Troubleshooting

### Issue: "No active sandbox"

**Cause**: `ensureSandbox` hasn't been called

**Fix**: Ensure `ensureSandbox` is called before using sandbox features:

```typescript
const handleSend = useCallback(async (content: string) => {
  if (!projectId) return;
  await ensureSandbox(); // <-- Make sure this is called
  await sendMessage(content, projectId);
}, [projectId, ensureSandbox, sendMessage]);
```

### Issue: Desktop/Terminal not starting

**Cause**: No active project is set in the store

**Fix**: Ensure `activeProjectId` is set before starting desktop/terminal.
The store actions early-return when `activeProjectId` is missing:

```typescript
await projectSandboxService.startDesktop(projectId);
```

## Verification Checklist

- [ ] AgentChat loads without errors
- [ ] `POST /projects/{id}/sandbox` called on first message
- [ ] Sandbox panel opens
- [ ] Terminal connects
- [ ] Desktop starts
- [ ] Tool execution shows output
- [ ] SSE events received

## Rollback

The project-scoped sandbox API is the active code path; there is no in-store
fallback to the legacy `sandboxService`. Rollback would require reintroducing
a `sandboxService` import and a v1 branch in `stores/sandbox.ts`.
