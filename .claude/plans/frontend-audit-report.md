# Frontend UI Audit Report

**Date**: 2026-03-27
**Total Files**: 646 .ts/.tsx files

## ESLint Issues Summary

**Total**: 4486 problems (21 errors, 4465 warnings)

### By Rule Type (Top 15)

| Rule | Count | Category |
|------|-------|----------|
| `@typescript-eslint/no-unsafe-member-access` | 1137 | Type Safety |
| `@typescript-eslint/no-unsafe-assignment` | 790 | Type Safety |
| `@typescript-eslint/no-unnecessary-condition` | 529 | Code Quality |
| `@typescript-eslint/no-explicit-any` | 470 | Type Safety |
| `@typescript-eslint/restrict-template-expressions` | 372 | Type Safety |
| `@typescript-eslint/no-floating-promises` | 296 | Async |
| `@typescript-eslint/no-misused-promises` | 222 | Async |
| `@typescript-eslint/no-deprecated` | 154 | Maintenance |
| `@typescript-eslint/no-unsafe-argument` | 114 | Type Safety |
| `@typescript-eslint/no-unsafe-call` | 107 | Type Safety |
| `@typescript-eslint/no-unsafe-return` | 48 | Type Safety |
| `@typescript-eslint/no-non-null-assertion` | 40 | Type Safety |
| `@typescript-eslint/no-redundant-type-constituents` | 27 | Type Safety |
| `@typescript-eslint/no-base-to-string` | 25 | Type Safety |
| `@typescript-eslint/no-unnecessary-type-conversion` | 24 | Code Quality |

### By Category

| Category | Count | Priority |
|----------|-------|----------|
| Type Safety (unsafe-*) | ~2700 | High |
| Unnecessary Conditions | 529 | Medium |
| Any Type Usage | 470 | High |
| Async/Promise Issues | 518 | High |
| Deprecated APIs | 154 | Medium |
| Template Expressions | 372 | Medium |

## Files With Most Issues (Top 20)

| File | Issues | Priority |
|------|--------|----------|
| `stores/agent/streamEventHandlers.ts` | 240 | Critical |
| `stores/agentV3_backup.ts` | 162 | High |
| `services/sandboxService.ts` | 156 | High |
| `stores/sandbox.ts` | 147 | High |
| `stores/agentV3.ts` | 138 | High |
| `pages/project/EnhancedSearch.tsx` | 108 | Medium |
| `components/agent/AgentDefinitionModal.tsx` | 99 | Medium |
| `pages/project/communities/index.tsx` | 95 | Medium |
| `components/artifact/ArtifactRenderer.tsx` | 93 | Medium |
| `pages/project/schema/EntityTypeList.tsx` | 85 | Medium |
| `components/provider/ProviderConfigModal.tsx` | 76 | Medium |
| `components/graph/CytoscapeGraph/CytoscapeGraph.tsx` | 68 | Medium |
| `components/graph/CytoscapeGraph/Viewport.tsx` | 60 | Medium |
| `utils/sseEventAdapter.ts` | 57 | Medium |
| `pages/project/EntitiesList.tsx` | 57 | Medium |
| `components/subagent/SubAgentModal.tsx` | 55 | Medium |
| `components/agent/sandbox/KasmVNCViewer.tsx` | 55 | Medium |
| `components/mcp-app/StandardMCPAppRenderer.tsx` | 53 | Medium |
| `pages/project/schema/EdgeTypeList.tsx` | 52 | Medium |
| `pages/project/schema/SchemaOverview.tsx` | 51 | Medium |

## Test Failures

**Summary**: 58 test files failed, 263 tests failed (2039 passed)

### Root Causes

1. **localStorage Mock Issues** (`useLocalStorage.test.ts`)
   - Mock not properly reset between tests
   - State leakage across test cases

2. **API Response Format Changes** (`api.test.ts`)
   - Response structure mismatch
   - Missing fields in expected objects

3. **WebSocket URL Construction** (`apiUrlMigration.test.ts`)
   - URL building logic changed
   - Port mismatch (8000 vs 3000)

4. **Component Rendering Issues**
   - Missing providers in test setup
   - Async rendering timing issues

## Action Plan

### Phase 2: Normalize (Immediate)
1. Fix top 10 files with most issues
2. Address type safety issues (unsafe-* rules)
3. Fix floating promises

### Phase 3: Polish
1. Remove unnecessary conditions
2. Replace `any` types with proper types
3. Fix deprecated API usage

### Phase 4: Critique
1. Code review all changes
2. Validate test coverage

### Phase 5: Harden
1. Security audit
2. Fix all failing tests
3. Final verification
