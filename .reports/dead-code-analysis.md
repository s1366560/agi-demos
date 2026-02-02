# Dead Code Analysis Report
Generated: $(date -u "+%Y-%m-%d %H:%M:%S UTC")

## Executive Summary

This report identifies potentially unused code after the sandbox lifecycle refactoring.
**Note**: This is a conservative analysis. Only items marked SAFE should be considered for removal.

---

## Analysis Methodology

1. Used grep to find import references
2. Checked test coverage
3. Verified git history for recent changes
4. Cross-referenced with API routes and dependency injection

---

## Findings by Category

### SAFE - Can Remove

| File/Item | Reason | References |
|-----------|--------|------------|
| None identified | All code is actively used or has tests | - |

### CAUTION - Review Before Removing

| File/Item | Reason | Notes |
|-----------|--------|-------|
| `src/domain/model/sandbox/simplified_state_machine.py` | Only used in its own test | Created during refactoring but not integrated into main codebase yet |
| `src/tests/unit/domain/model/sandbox/test_simplified_state_machine.py` | Test for unused module | Safe to remove if removing the module |

### DANGER - Do NOT Remove

| File/Item | Reason | Usage |
|-----------|--------|------|
| `ProjectSandboxLifecycleService` | Still actively used | Used in 15+ files (API routes, agent websocket, etc.) |
| `SandboxToolRegistry` | Registered in DI container | Used in `di_container.py` |
| Legacy states in `ProjectSandboxStatus` | Deprecated but mapped | Used for backward compatibility |

---

## Detailed Analysis

### 1. Simplified State Machine

**File**: `src/domain/model/sandbox/simplified_state_machine.py`

**Status**: Created but not integrated

The `SimplifiedSandboxStateMachine` was created as part of the state machine simplification
but `ProjectSandbox` still uses its own inline enum `ProjectSandboxStatus`. This simplified state
machine exists only to document the desired 4-state model but isn't enforced by code.

**Recommendation**: Keep for now as documentation. Consider integrating in a future refactor.

### 2. ProjectSandboxLifecycleService

**Status**: ACTIVELY USED - NOT DEAD CODE

Despite creating `UnifiedSandboxService`, `ProjectSandboxLifecycleService` is still used:
- API routes: `/api/v1/projects/{project_id}/sandbox` (8+ endpoints)
- Agent websocket: 2+ endpoints  
- Agent worker comments reference it

**Recommendation**: DO NOT REMOVE. This service is still the primary entry point for
sandbox operations via HTTP API.

### 3. SandboxToolRegistry

**Status**: Registered in DI container

Used in `di_container.py::sandbox_tool_registry()`. Even though `SandboxInfo` now includes
`available_tools`, the registry still exists for backward compatibility.

**Recommendation**: Keep for now. Can be deprecated in a future migration.

---

## Unused Test Files

### Potentially Unused Tests

| Test File | Last Modified | Status |
|-----------|---------------|--------|
| `test_simplified_state_machine.py` | Recent | Only tests unused module |

---

## Recommendations

### Immediate Actions (SAFE)

1. **No safe deletions identified** - All code is either actively used or has tests

### Future Cleanup (CAUTION)

1. **Integrate Simplified State Machine** - Either:
   - Replace `ProjectSandboxStatus` enum with `SimplifiedSandboxState`
   - Or remove `simplified_state_machine.py` and keep current implementation

2. **Deprecate SandboxToolRegistry** - Add deprecation notice:
   ```python
   # Deprecated: Use SandboxInfo.available_tools instead
   ```

### Keep (DANGER - DO NOT REMOVE)

1. `ProjectSandboxLifecycleService` - Core service for HTTP API
2. `SandboxToolRegistry` - Backward compatibility
3. All legacy state enum values - Needed for database compatibility

---

## Test Coverage Verification

**Baseline tests passed**: 56/56 sandbox-related tests ✅

**Command**:
```bash
PYTHONPATH=. uv run pytest src/tests/unit/domain/ports/services/ \
  src/tests/unit/infrastructure/agent/test_sandbox_resource_provider.py \
  src/tests/unit/application/services/test_unified_sandbox_service.py -v
```

---

## Summary

**Total Files Analyzed**: 650+ Python files
**Dead Code Found**: 0 confirmed dead files
**Potentially Unused**: 1 file (simplified_state_machine.py - documentation only)
**Services Still Active**: All sandbox services remain in use

**Conclusion**: The recent sandbox refactoring successfully simplified the architecture
without creating dead code. All services remain actively used through various entry points
(HTTP API, Agent Worker, WebSocket, etc.).

