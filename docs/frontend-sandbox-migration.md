# Frontend Sandbox Migration Guide

## Overview

The backend has been refactored to support **project-dedicated persistent sandboxes**. Each project now has exactly one sandbox that:
- Is created lazily on first use
- Remains running for the project's lifetime
- Auto-recovers if unhealthy

This guide explains how to migrate the frontend from sandbox ID-based management to project-scoped management.

## API Changes

### Old API (Sandbox ID-based)
```
POST   /api/v1/sandbox/create
GET    /api/v1/sandbox/{sandbox_id}
DELETE /api/v1/sandbox/{sandbox_id}
POST   /api/v1/sandbox/{sandbox_id}/desktop
POST   /api/v1/sandbox/{sandbox_id}/terminal
```

### New API (Project-scoped)
```
GET    /api/v1/projects/{project_id}/sandbox
POST   /api/v1/projects/{project_id}/sandbox
GET    /api/v1/projects/{project_id}/sandbox/health
POST   /api/v1/projects/{project_id}/sandbox/execute
POST   /api/v1/projects/{project_id}/sandbox/restart
DELETE /api/v1/projects/{project_id}/sandbox
POST   /api/v1/projects/{project_id}/sandbox/desktop
POST   /api/v1/projects/{project_id}/sandbox/terminal
```

## Migration Steps

### Step 1: Add New Service

File: `web/src/services/projectSandboxService.ts` (already created)

This service provides:
- `ensureSandbox(projectId)` - Get or create project's sandbox
- `executeTool(projectId, toolName, args)` - Execute MCP tools
- `startDesktop(projectId)` - Start desktop for project
- `startTerminal(projectId)` - Start terminal for project
- `healthCheck(projectId)` - Check sandbox health

### Step 2: Update AgentChat.tsx

Replace the `ensureSandbox` function:

```typescript
// OLD CODE
import { sandboxService } from '../../services/sandboxService';

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

// NEW CODE
import { projectSandboxService } from '../../services/projectSandboxService';

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

### Step 3: Update Sandbox Store

File: `web/src/stores/sandbox.ts`

Update desktop/terminal actions to use projectId:

```typescript
// Add projectId to state
interface SandboxState {
  // ... existing state
  activeProjectId: string | null;
}

// Update actions
startDesktop: async () => {
  const { activeProjectId } = get();
  if (!activeProjectId) {
    console.warn("Cannot start desktop: no active project");
    return;
  }

  set({ isDesktopLoading: true });

  try {
    const status = await projectSandboxService.startDesktop(activeProjectId);
    set({ desktopStatus: status, isDesktopLoading: false });
  } catch (error) {
    console.error("Failed to start desktop:", error);
    set({ isDesktopLoading: false });
    throw error;
  }
},
```

### Step 4: Update SandboxPanel Components

Components can use the new hooks from `AgentChatMigration.tsx`:

```typescript
import { useProjectDesktop, useProjectTerminal } from './AgentChatMigration';

function SandboxPanel({ projectId }: { projectId: string }) {
  const { startDesktop, stopDesktop } = useProjectDesktop(projectId);
  const { startTerminal, stopTerminal } = useProjectTerminal(projectId);

  // Use these functions instead of sandboxService methods
}
```

### Step 5: Update Types

File: `web/src/types/sandbox.ts`

Add new types for project sandbox:

```typescript
export interface ProjectSandbox {
  sandbox_id: string;
  project_id: string;
  tenant_id: string;
  status: 'pending' | 'creating' | 'running' | 'unhealthy' | 'stopped' | 'terminated' | 'error';
  endpoint?: string;
  websocket_url?: string;
  mcp_port?: number;
  desktop_port?: number;
  terminal_port?: number;
  desktop_url?: string;
  terminal_url?: string;
  is_healthy: boolean;
  error_message?: string;
}
```

## Backward Compatibility

The old sandbox API (`/api/v1/sandbox/*`) remains available for backward compatibility. Existing code will continue to work.

However, new features (auto-recovery, health monitoring) are only available through the new project-scoped API.

## Testing

### Test New Service

```typescript
// Test ensureSandbox
const sandbox = await projectSandboxService.ensureSandbox('proj-123');
console.log('Sandbox:', sandbox.sandbox_id, 'Status:', sandbox.status);

// Test tool execution
const result = await projectSandboxService.executeTool('proj-123', {
  tool_name: 'bash',
  arguments: { command: 'ls -la' }
});
console.log('Output:', result.content);

// Test desktop
const desktop = await projectSandboxService.startDesktop('proj-123');
console.log('Desktop URL:', desktop.url);
```

### Verify Migration

1. Open Agent Chat page
2. Check browser network tab for calls to `/api/v1/projects/{project_id}/sandbox`
3. Verify sandbox is created and tools execute successfully
4. Verify desktop/terminal services work

## Benefits

1. **Simplified Logic** - No need to manage sandbox IDs
2. **Better Reliability** - Auto-recovery handled by backend
3. **Consistent State** - Single sandbox per project
4. **Health Monitoring** - Backend handles health checks

## Timeline

- Phase 1: Add new service and types (1 day)
- Phase 2: Update AgentChat.tsx (1 day)
- Phase 3: Update SandboxPanel components (1-2 days)
- Phase 4: Testing and validation (1 day)

## Migration Checklist

- [ ] Create `projectSandboxService.ts`
- [ ] Update `AgentChat.tsx` ensureSandbox function
- [ ] Update `sandbox.ts` store actions
- [ ] Update `SandboxPanel.tsx` components
- [ ] Add new types to `sandbox.ts`
- [ ] Test tool execution
- [ ] Test desktop service
- [ ] Test terminal service
- [ ] Test SSE events
- [ ] Update documentation
