# Dead Code Analysis Report

## Analysis Date: 2025-02-03

## Executive Summary

This report identifies dead code, obsolete tests, and unused exports in the frontend codebase.
Current test status: **44 failing test files, 181 failing tests**

---

## 1. Obsolete Test Files (SAFE TO DELETE)

### 1.1 Tests for Non-Existent Exports

| Test File | Issue | Status |
|-----------|-------|--------|
| `src/test/components/antd-lazy.test.tsx` | Tests for `LazySpinner` but export is `LazySpin` | OBSOLETE |
| `src/test/components/virtualized-memory-list.test.tsx` | Tests for `VirtualizedMemoryList` from ProjectOverview that doesn't export it | OBSOLETE |
| `src/test/components/barrelExports.test.tsx` | Tests for exports that don't exist (MessageList, InputArea, ThinkingChain, ToolCard, PlanViewer) | NEEDS UPDATE |

### 1.2 Component Export Mismatches

The following tests expect exports that don't match actual barrel exports:

**Expected by test but not exported:**
- `MessageList` (actual export is `MessageArea`)
- `InputArea` (actual export is `InputBar`)
- `ThinkingChain` (not exported from barrel, only exists as file)
- `ToolCard` (not exported from barrel, only exists as file)
- `PlanViewer` (actual export is `ExecutionPlanViewer`)
- `ExecutionDetailsPanel` (not exported from barrel)

---

## 2. Unused Dependencies (From depcheck)

```
Unused devDependencies:
* @tailwindcss/postcss
* @vitest/coverage-v8
* autoprefixer
* postcss
* tailwindcss
* vite-plugin-istanbul

Missing dependencies:
* @testing-library/user-event (used in tests but not in package.json)
```

---

## 3. Potentially Unused Source Files (From knip)

### 3.1 Unused Files (64 found by knip)

```
e2e/base.ts
src/components/agent/AgentChatHooks.ts
src/components/agent/AgentChatInputArea.tsx
src/components/agent/chat/ChatArea.tsx
src/components/agent/ExecutionDetailsPanel.tsx
src/components/agent/sandbox/index.ts
src/components/agent/sandbox/SandboxControlPanel.tsx
src/components/agent/sandbox/SandboxPanel.tsx
src/components/agent/ThinkingChain.tsx
src/components/agent/ThoughtBubble.tsx
src/components/agent/ToolCard.tsx
src/components/agent/WorkPlanCard.tsx
src/components/index.ts (root barrel - deprecated)
src/components/layout/AgentSidebar.tsx
src/components/layout/TenantSidebar.tsx
src/components/MemoryCreateModal.tsx
src/components/project/MemoryDetailModal.tsx
src/components/project/MemoryManager.tsx
src/components/project/search/index.ts
src/components/project/search/SearchHeader.tsx
src/components/project/VirtualizedMemoryList.tsx
src/components/shared/index.ts
src/components/shared/layouts/AppLayout.tsx
src/components/shared/layouts/index.ts
src/components/shared/layouts/Layout.tsx
src/components/shared/layouts/ResponsiveLayout.tsx
src/components/shared/modals/index.ts
src/components/shared/ui/index.ts
src/components/shared/ui/NotificationPanel.tsx
src/components/tenant/ProjectCreateModal.tsx
src/components/tenant/ProjectManager.tsx
src/components/tenant/ProjectSettingsModal.tsx
src/components/tenant/TenantCreateModal.tsx
src/components/tenant/TenantSelector.tsx
src/hooks/useConversationStatuses.ts
src/hooks/useDateFormatter.ts
src/hooks/useDebounce.ts
src/hooks/useMediaQuery.ts
src/hooks/useModal.ts
src/hooks/usePagination.ts
src/hooks/useSearchState.ts
src/hooks/useWebSocket.ts
src/layouts/AgentLayout.tsx
src/pages/SpaceDashboard.tsx
src/pages/SpaceListPage.tsx
src/services/artifactService.ts
```

**NOTE:** Knip marks these as unused because it only analyzes production code.
These may be used by tests or through dynamic imports.

---

## 4. Failing Test Analysis

### 4.1 Test Failures by Category

| Category | Count | Test Files |
|----------|-------|------------|
| Component Export Tests | 8 | barrelExports.test.tsx |
| Obsolete Component Tests | 3 | antd-lazy.test.tsx, virtualized-memory-list.test.tsx, SidebarNavItem.test.tsx |
| Hook Tests | 18 | useLocalStorage.test.ts, useDateFormatter.test.ts, useMediaQuery.test.ts, etc. |
| Layout Tests | 11 | AgentLayout.test.tsx, ProjectLayout.test.tsx, TenantLayout.test.tsx |
| API Tests | 2 | api.test.ts |
| Page Tests | 4 | McpServerList.test.tsx, SubAgentList.test.tsx, etc. |
| Integration Tests | 15 | agentSSE.test.ts, etc. |
| Performance Tests | 9 | reactMemo.test.tsx, TextDeltaPerformance.test.ts |
| Component Tests | 111 | Various component tests |

### 4.2 Sandbox Panel Desktop Test

**File:** `src/test/components/agent/sandbox/SandboxPanelDesktop.test.tsx`

**Status:** Components still exist, test has minor issues with:
- Duplicate "Connecting" text in the document (needs more specific selector)
- Terminal start button callback not being called (button finding logic issue)

**Action:** FIX rather than delete - the components `SandboxPanel`, `RemoteDesktopViewer`, and `SandboxControlPanel` are actively used.

---

## 5. Recommended Actions

### 5.1 SAFE TO DELETE (High Confidence)

1. **`src/test/components/antd-lazy.test.tsx`**
   - Tests for exports that don't exist (`LazySpinner` vs `LazySpin`)
   - Tests for features that don't match implementation

2. **`src/test/components/virtualized-memory-list.test.tsx`**
   - Tests for `VirtualizedMemoryList` export that doesn't exist in ProjectOverview

3. **Unused devDependencies** (from package.json):
   - `@tailwindcss/postcss`
   - `@vitest/coverage-v8`
   - `autoprefixer`
   - `postcss`
   - `tailwindcss`
   - `vite-plugin-istanbul`

### 5.2 NEEDS UPDATE (Medium Confidence)

1. **`src/test/components/barrelExports.test.tsx`**
   - Update export expectations to match actual exports
   - Or remove tests for non-existent exports

### 5.3 INVESTIGATE FURTHER (Low Confidence)

1. **Hook tests** (useLocalStorage, useDateFormatter, useMediaQuery, etc.)
   - Tests may be failing due to mock setup issues, not obsolete code
   - Need to verify if hooks are still in use

2. **Layout tests** (AgentLayout, ProjectLayout, TenantLayout)
   - Components may have been refactored
   - Tests need updating to match new component structure

---

## 6. Files NOT to Delete (Critical)

- Sandbox components: `SandboxPanel.tsx`, `RemoteDesktopViewer.tsx`, `SandboxControlPanel.tsx`
  - These are actively used in `SandboxSection.tsx`
- Agent core components in `src/components/agent/`
- All store files in `src/stores/`
- All service files in `src/services/`

---

## 7. Test Results Summary

```
Test Files  44 failed | 99 passed | 3 skipped (146)
Tests       181 failed | 1892 passed | 58 skipped (2131)
```

**Pass Rate:** 88.8% (1892/2131 tests pass)

---

## 8. Next Steps

1. Delete obsolete test files (Section 5.1)
2. Update barrelExports test to match actual exports
3. Fix or update failing hook tests
4. Fix SandboxPanelDesktop.test.tsx selector issues
5. Remove unused devDependencies from package.json
6. Re-run tests to verify improvements

---

## 9. Risk Assessment

| Action | Risk Level | Impact |
|--------|------------|--------|
| Delete antd-lazy.test.tsx | LOW | File tests non-existent exports |
| Delete virtualized-memory-list.test.tsx | LOW | File tests non-existent component export |
| Remove unused devDependencies | LOW | Reduces bundle size |
| Update barrelExports.test.tsx | LOW | Aligns tests with reality |
| Fix hook tests | MEDIUM | Hooks may still be in use |
| Fix layout tests | MEDIUM | Layouts may have been refactored |
