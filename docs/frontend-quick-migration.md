# Frontend Quick Migration Guide

## Quick Start (5 minutes)

### 1. Import New Service

```typescript
// In AgentChat.tsx, add:
import { projectSandboxService } from '../../services/projectSandboxService';
```

### 2. Replace ensureSandbox Function

```typescript
// REPLACE this in AgentChat.tsx:
const ensureSandbox = useCallback(async () => {
  if (activeSandboxId) return activeSandboxId;
  if (!projectId) return null;

  try {
    const { sandboxes } = await sandboxService.listSandboxes(projectId);
    if (sandboxes.length > 0 && sandboxes[0].status === 'running') {
      setSandboxId(sandboxes[0].id);
      return sandboxes[0].id;
    }
    const { sandbox } = await sandboxService.createSandbox({ project_id: projectId });
    setSandboxId(sandbox.id);
    return sandbox.id;
  } catch (error) {
    console.error('[AgentChat] Failed to ensure sandbox:', error);
    return null;
  }
}, [activeSandboxId, projectId, setSandboxId]);

// WITH this:
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

### 3. Update Store Actions (Optional but Recommended)

```typescript
// In stores/sandbox.ts, update:
startDesktop: async () => {
  const { activeProjectId, activeSandboxId } = get();
  
  // Prefer project-scoped API if we have projectId
  if (activeProjectId) {
    const status = await projectSandboxService.startDesktop(activeProjectId);
    set({ desktopStatus: status });
    return;
  }
  
  // Fallback to old API
  if (activeSandboxId) {
    const status = await sandboxService.startDesktop(activeSandboxId);
    set({ desktopStatus: status });
  }
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

**Cause**: Using old sandbox ID with new API

**Fix**: Use projectId:

```typescript
// Old
await sandboxService.startDesktop(sandboxId);

// New
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

If needed, simply revert to the old `ensureSandbox` implementation using `sandboxService`.

The old API endpoints remain available and working.
