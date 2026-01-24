# Sandbox Event Integration Plan

## Overview

Connect sandbox tool detection handlers to the agent event stream, enabling automatic UI updates when the agent executes sandbox tools (read/write/edit/glob/grep/bash).

## Current Architecture Analysis

### What's Already Working

1. **Backend SSE Events** - Complete and correct:
   - `ACT`: `{ tool_name, tool_input, call_id, status }`
   - `OBSERVE`: `{ tool_name, result/error, duration_ms, call_id }`

2. **Sandbox Store** (`sandbox.ts`) - Ready to receive events:
   - `SANDBOX_TOOLS = ["read", "write", "edit", "glob", "grep", "bash"]`
   - `onToolStart(toolName, input, callId)` - auto opens panel
   - `onToolEnd(callId, output, error, durationMs)` - updates execution

3. **Detection Hooks** (`useSandboxDetection.ts`) - Handlers created:
   - `useSandboxAgentHandlers(sandboxId)` returns `{ onAct, onObserve }`

4. **agentV3Store** (`agentV3.ts:644-750`) - Event processing:
   - `onAct` creates ToolCall, tracks in activeToolCalls Map
   - `onObserve` updates results, calculates duration

### The Gap

The sandbox handlers in `AgentChatV3.tsx` (lines 151-152) are created but **not connected** to the event stream. The `sendMessage` method doesn't provide a way to inject additional handlers.

## Design Decision: Callback Injection Pattern

**Chosen Approach**: Add optional `additionalHandlers` parameter to `sendMessage`

**Rationale**:
- Minimal code changes (2 files)
- Maintains loose coupling - agentV3Store doesn't import sandbox
- Extensible for future integrations
- Follows existing React callback patterns

**Rejected Alternatives**:
- Event Emitter: Over-engineered for this use case
- Direct store subscription: Creates tight coupling
- Middleware pattern: Too complex for current needs

## Implementation Plan

### Step 1: Extend agentV3Store Types

**File**: `web/src/stores/agentV3.ts`

Add interface for additional handlers:
```typescript
interface AdditionalAgentHandlers {
  onAct?: (event: ActEvent) => void;
  onObserve?: (event: ObserveEvent) => void;
}
```

### Step 2: Modify sendMessage Signature

**File**: `web/src/stores/agentV3.ts`

Update `sendMessage` to accept additional handlers:
```typescript
sendMessage: (
  content: string, 
  projectId: string, 
  additionalHandlers?: AdditionalAgentHandlers
) => Promise<string | null>
```

### Step 3: Invoke Additional Handlers in Event Processing

**File**: `web/src/stores/agentV3.ts`

In `onAct` handler (around line 700):
```typescript
// After existing logic
additionalHandlers?.onAct?.(event);
```

In `onObserve` handler (around line 750):
```typescript
// After existing logic
additionalHandlers?.onObserve?.(event);
```

### Step 4: Connect Handlers in AgentChatV3

**File**: `web/src/pages/project/AgentChatV3.tsx`

Update `handleSend` to pass sandbox handlers:
```typescript
const { onAct, onObserve } = useSandboxAgentHandlers(activeSandboxId);

const handleSend = async (content: string) => {
  const newConversationId = await sendMessage(content, projectId, {
    onAct,
    onObserve
  });
  // ...
};
```

### Step 5: Fix Event Data Mapping

**File**: `web/src/hooks/useSandboxDetection.ts`

Update `onObserve` to handle the actual event structure:
```typescript
const onObserve = useCallback((event) => {
  // Backend sends: { observation, error, duration_ms, call_id }
  // But call_id may be missing, use toolName from stack
  handleToolEnd(
    event.data.call_id,
    event.data.observation || event.data.result,
    event.data.error,
    event.data.duration_ms
  );
}, [handleToolEnd]);
```

## Files to Modify

| File | Changes |
|------|---------|
| `web/src/stores/agentV3.ts` | Add AdditionalAgentHandlers interface, update sendMessage signature, invoke handlers |
| `web/src/pages/project/AgentChatV3.tsx` | Remove underscore prefixes, pass handlers to sendMessage |
| `web/src/hooks/useSandboxDetection.ts` | Fix event data field mapping |

## Data Flow After Implementation

```
Agent SSE Event Stream
         │
         ▼
agentService.chat(handler)
         │
         ▼
AgentStreamHandler
         │
    ┌────┴────┐
    ▼         ▼
onAct      onObserve
    │         │
    ├─────────┤
    │         │
    ▼         ▼
agentV3     additionalHandlers
Store          │
Update         ▼
          sandboxStore
          (auto-open panel,
           track executions)
```

## Verification Plan

1. **Unit Test**: Verify sandbox handlers are called with correct event data
2. **Integration Test**:
   - Start agent chat
   - Send message that triggers sandbox tool (e.g., "read file X")
   - Verify: Sandbox panel opens automatically
   - Verify: Tool execution appears in Output tab
   - Verify: Terminal tab shows sandbox connection
3. **Edge Cases**:
   - Multiple concurrent tool calls
   - Tool execution errors
   - Missing call_id in events

## Future Considerations

1. **Sandbox ID Detection**: Currently using `activeSandboxId` from store. May need to extract from agent context or tool parameters.
2. **Tool-specific Visualization**: Different UI for file operations vs bash commands.
3. **Streaming Output**: For long-running bash commands, may want real-time output streaming.
