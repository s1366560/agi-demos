# Dead Code Analysis Report: AgentChatLegacy.tsx

**Date**: 2026-01-28
**Tools**: knip 5.82.1, depcheck 1.4.7, ts-prune, manual analysis
**Target File**: `src/pages/project/AgentChatLegacy.tsx`
**Related Files**: `src/hooks/useAgentChat.ts`, `src/components/agent/chat/ChatArea.tsx`

---

## Executive Summary

**Status**: NO DEAD CODE FOUND
**Risk Level**: SAFE
**Recommendation**: No deletions recommended

All code in `AgentChatLegacy.tsx` is actively used. The file is the main page component for the Agent Chat interface and properly utilizes all imported dependencies and destructured values from the `useAgentChat` hook.

---

## Tool Results

### knip (5.82.1)

```
No issues found for AgentChatLegacy
```

### depcheck (1.4.7)

```
All dependencies are used
```

### ts-prune

Found unused exports in related files:
- `src/hooks/useAgentChat.ts:18 - shouldShowExecutionPlan` (exported but not imported anywhere)

---

## Manual Analysis

### Imports Analysis

All imports are actively used:

| Import | Usage Count | Status |
|--------|-------------|--------|
| `React` | 3+ | USED |
| `memo` | 1 | USED |
| `useMemo` | 1 | USED |
| `Modal` | 1 | USED |
| `Input` | 1 | USED |
| `Form` | 1 | USED |
| `useAgentChat` | 1 | USED |
| `ChatArea` | 1 | USED |
| `FloatingInputBar` | 1 | USED |
| `ChatHistorySidebar` | 1 | USED |

### Destructured Variables from useAgentChat

All destructured values are actively used in the component:

| Variable | Usage | Status |
|----------|-------|--------|
| `projectId` | Conditional render, handlers | USED |
| `currentConversation` | Props, conditions, handlers | USED |
| `conversations` | useMemo transform | USED |
| `timeline` | Passed to ChatArea | USED |
| `messagesLoading` | Passed to ChatArea | USED |
| `isStreaming` | Multiple locations | USED |
| `inputValue` | Passed to FloatingInputBar | USED |
| `setInputValue` | Passed to FloatingInputBar | USED |
| `historySidebarOpen` | Conditional rendering | USED |
| `setHistorySidebarOpen` | Button handlers | USED |
| `searchQuery` | Passed to ChatHistorySidebar | USED |
| `setSearchQuery` | Passed to ChatHistorySidebar | USED |
| `showPlanEditor` | Passed to ChatArea | USED |
| `showEnterPlanModal` | Modal visibility | USED |
| `setShowEnterPlanModal` | Modal handlers | USED |
| `planForm` | Form instance | USED |
| `currentWorkPlan` | Passed to ChatArea | USED |
| `currentStepNumber` | Passed to ChatArea | USED |
| `executionTimeline` | Passed to ChatArea | USED |
| `toolExecutionHistory` | Passed to ChatArea | USED |
| `matchedPattern` | Passed to ChatArea | USED |
| `currentPlan` | Passed to ChatArea, handlers | USED |
| `planModeStatus` | Passed to ChatArea, FloatingInputBar | USED |
| `planLoading` | Modal, FloatingInputBar | USED |
| `hasEarlierMessages` | Passed to ChatArea | USED |
| `messagesEndRef` | Passed to ChatArea | USED |
| `scrollContainerRef` | Passed to ChatArea | USED |
| `handleSend` | FloatingInputBar | USED |
| `handleStop` | FloatingInputBar | USED |
| `handleTileClick` | Passed to ChatArea | USED |
| `handleSelectConversation` | ChatHistorySidebar | USED |
| `handleNewChat` | ChatHistorySidebar | USED |
| `handleViewPlan` | ChatArea | USED |
| `handleExitPlanMode` | ChatArea | USED |
| `handleUpdatePlan` | ChatArea | USED |
| `handleEnterPlanMode` | FloatingInputBar | USED |
| `handleEnterPlanSubmit` | Modal | USED |
| `handleLoadEarlier` | ChatArea | USED |

---

## Related Finding: Unused Export in useAgentChat

### Location

`src/hooks/useAgentChat.ts:18`

### Issue

`shouldShowExecutionPlan` function is exported but never imported anywhere in the codebase.

### Function Code

```typescript
export function shouldShowExecutionPlan(
  workPlan: WorkPlan | null | undefined,
  executionTimeline: TimelineStep[],
  toolExecutionHistory: ToolExecution[]
): boolean {
  if (workPlan && workPlan.steps && workPlan.steps.length > 1) {
    return true;
  }
  if (toolExecutionHistory.length > 1) {
    return true;
  }
  if (executionTimeline.length > 1) {
    return true;
  }
  return false;
}
```

### Recommendation

**SAFE TO REMOVE** - This export can be removed as it is not used anywhere. If needed in the future, it can be extracted from the hook or made a named export.

**Severity**: SAFE (utility function, no side effects)

---

## Code Quality Observations

### Positive Findings

1. **Clean Destructuring**: All values from `useAgentChat` hook are properly utilized
2. **Proper Component Composition**: Uses modular components (`ChatArea`, `FloatingInputBar`, `ChatHistorySidebar`)
3. **Type Safety**: Uses TypeScript for type inference and type imports
4. **Performance Optimization**: Uses `useMemo` for conversation transformation
5. **Proper Memoization**: Component wrapped with `React.memo`

### Potential Improvements (Optional)

1. **File Naming**: Component is named `AgentChatLegacy.tsx` - consider if "Legacy" suffix is still appropriate given the recent refactoring
2. **Direct Export**: The file exports both `AgentChat` (named) and `default` - could simplify to one export pattern

---

## Conclusion

**No dead code found in AgentChatLegacy.tsx.** The file is clean, well-structured, and all code is actively used.

**One related finding**: `shouldShowExecutionPlan` in `src/hooks/useAgentChat.ts` is exported but unused - safe to remove.

---

## Test Verification

Baseline tests passed:
- `src/test/hooks/useAgentChat.test.ts`: 2/2 passing

No page-level tests exist for `AgentChat.tsx` - this is acceptable as the component is primarily tested through hook tests and E2E tests.

