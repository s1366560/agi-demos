# Frontend Sandbox Integration Analysis

## Current Integration Status

### Existing Frontend Architecture

#### 1. Services Layer

**sandboxService.ts** (`web/src/services/sandboxService.ts`)
- Uses **OLD** sandbox ID-based API (`/api/v1/sandbox/{id}`)
- Methods: `createSandbox`, `getSandbox`, `listSandboxes`, `deleteSandbox`
- Desktop/Terminal: `startDesktop(sandboxId)`, `startTerminal(sandboxId)`
- **Status**: ⚠️ Needs migration

**sandboxSSEService.ts** (`web/src/services/sandboxSSEService.ts`)
- Already uses project-scoped SSE endpoint (`/api/v1/sandbox/events/{project_id}`)
- **Status**: ✅ Compatible with new backend

**sandboxWebSocketUtils.ts**
- Utility functions for building WebSocket URLs
- **Status**: ✅ No changes needed

#### 2. Store Layer

**sandbox.ts** (`web/src/stores/sandbox.ts`)
- State: `activeSandboxId`, `activeProjectId`
- Actions: `startDesktop()`, `stopDesktop()`, `startTerminal()`, `stopTerminal()`
- Currently uses `sandboxService` which requires sandboxId
- **Status**: ⚠️ Needs migration to use `projectSandboxService`

#### 3. Component Layer

**AgentChat.tsx** (`web/src/pages/project/AgentChat.tsx`)
- Has `ensureSandbox()` function that:
  1. Calls `sandboxService.listSandboxes(projectId)`
  2. If none exists, calls `sandboxService.createSandbox({project_id})`
- **Status**: ⚠️ Primary migration target

**SandboxPanel.tsx** (`web/src/components/agent/sandbox/SandboxPanel.tsx`)
- Props: `sandboxId`, `desktopStatus`, `terminalStatus`
- Uses callbacks: `onDesktopStart`, `onTerminalStart`
- **Status**: ⚠️ Needs to support projectId-based operations

**SandboxTerminal.tsx**
- Uses `sandboxId` for WebSocket connection
- **Status**: ✅ Works with existing sandboxId

**RemoteDesktopViewer.tsx**
- Uses desktop URL from status
- **Status**: ✅ No changes needed

### Integration Points

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend Architecture                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  AgentChat.tsx                                               │
│  ├─ ensureSandbox() ──► sandboxService.listSandboxes()     │
│  │                      sandboxService.createSandbox()      │
│  │                                                           │
│  └─ sendMessage() ────► uses sandboxId from store           │
│                                                              │
│  SandboxPanel.tsx                                            │
│  ├─ startDesktop() ───► sandboxService.startDesktop()       │
│  └─ startTerminal() ──► sandboxService.startTerminal()      │
│                                                              │
│  sandbox.ts (Store)                                          │
│  ├─ activeSandboxId: string | null                          │
│  ├─ activeProjectId: string | null                          │
│  └─ startDesktop() ───► sandboxService.startDesktop()       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Backend API                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  OLD API (Current)              NEW API (Project-scoped)    │
│  ───────────────                ─────────────────────────   │
│  POST /sandbox/create           POST /projects/{id}/sandbox │
│  GET  /sandbox/{id}             GET  /projects/{id}/sandbox │
│  POST /sandbox/{id}/desktop     POST /projects/{id}/desktop │
│  POST /sandbox/{id}/terminal    POST /projects/{id}/terminal│
│                                                              │
│  SSE: /sandbox/events/{project_id} ✅ (Same)                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Migration Strategy

### Phase 1: Add New Service (✅ Completed)

Created `web/src/services/projectSandboxService.ts`:
- `ensureSandbox(projectId)` - Get or create project's sandbox
- `executeTool(projectId, toolName, args)` - Execute MCP tools
- `startDesktop(projectId)` - Start desktop for project
- `startTerminal(projectId)` - Start terminal for project

### Phase 2: Create Migration Hooks (✅ Completed)

Created `web/src/components/agent/AgentChatMigration.tsx`:
- `useEnsureProjectSandbox(projectId)` - Replacement for ensureSandbox
- `useProjectDesktop(projectId)` - Project-scoped desktop management
- `useProjectTerminal(projectId)` - Project-scoped terminal management

### Phase 3: Update Components (⏳ Pending)

#### AgentChat.tsx
```typescript
// BEFORE
import { sandboxService } from '../../services/sandboxService';

const ensureSandbox = useCallback(async () => {
  if (activeSandboxId) return activeSandboxId;
  if (!projectId) return null;

  const { sandboxes } = await sandboxService.listSandboxes(projectId);
  if (sandboxes.length > 0) {
    setSandboxId(sandboxes[0].id);
    return sandboxes[0].id;
  }
  const { sandbox } = await sandboxService.createSandbox({ project_id: projectId });
  setSandboxId(sandbox.id);
  return sandbox.id;
}, [activeSandboxId, projectId, setSandboxId]);

// AFTER
import { projectSandboxService } from '../../services/projectSandboxService';

const ensureSandbox = useCallback(async () => {
  if (activeSandboxId) return activeSandboxId;
  if (!projectId) return null;

  const sandbox = await projectSandboxService.ensureSandbox(projectId);
  setSandboxId(sandbox.sandbox_id);
  return sandbox.sandbox_id;
}, [activeSandboxId, projectId, setSandboxId]);
```

#### sandbox.ts Store
```typescript
// Add to actions:
startDesktop: async () => {
  const { activeProjectId } = get();
  if (!activeProjectId) return;
  
  const status = await projectSandboxService.startDesktop(activeProjectId);
  set({ desktopStatus: status });
}
```

## API Compatibility Matrix

| Feature | Old API | New API | Status |
|---------|---------|---------|--------|
| Create Sandbox | ✅ | ✅ | Both work |
| Get Sandbox | ✅ | ✅ | New uses projectId |
| List Sandboxes | ✅ | ✅ | New has tenant endpoint |
| Delete Sandbox | ✅ | ✅ | Both work |
| Start Desktop | ✅ | ✅ | New uses projectId |
| Start Terminal | ✅ | ✅ | New uses projectId |
| Execute Tool | ❌ | ✅ | Only in new API |
| Health Check | ❌ | ✅ | Only in new API |
| Auto-recovery | ❌ | ✅ | Backend feature |
| SSE Events | ✅ | ✅ | Same endpoint |

## Files Modified/Created

### New Files (✅ Created)
1. `web/src/services/projectSandboxService.ts` - New project-scoped service
2. `web/src/components/agent/AgentChatMigration.tsx` - Migration hooks
3. `docs/frontend-sandbox-migration.md` - Migration guide
4. `docs/frontend-integration-analysis.md` - This document

### Files to Modify (⏳ Pending)
1. `web/src/pages/project/AgentChat.tsx` - Update ensureSandbox
2. `web/src/stores/sandbox.ts` - Update actions to use projectId
3. `web/src/types/sandbox.ts` - Add ProjectSandbox type

## Testing Plan

### Unit Tests
```bash
# Test new service
npm test -- projectSandboxService.test.ts

# Test updated components
npm test -- AgentChat.test.tsx
npm test -- sandboxStore.test.ts
```

### Integration Tests
1. Open Agent Chat page
2. Verify `POST /projects/{id}/sandbox` is called
3. Verify tool execution works
4. Verify desktop starts
5. Verify terminal connects
6. Verify SSE events are received

## Rollback Plan

If issues occur:
1. Revert to using `sandboxService` instead of `projectSandboxService`
2. The old API endpoints remain available
3. No database migration needed for rollback

## Benefits After Migration

1. **Simpler Code** - No need to track sandboxId, just use projectId
2. **Better UX** - Sandbox auto-recovery handled by backend
3. **More Features** - Health checks, tool execution API
4. **Consistent State** - Single sandbox per project guarantee

## Timeline Estimate

| Task | Effort |
|------|--------|
| Update AgentChat.tsx | 2 hours |
| Update sandbox store | 2 hours |
| Update SandboxPanel | 1 hour |
| Testing | 2 hours |
| **Total** | **7 hours** |
