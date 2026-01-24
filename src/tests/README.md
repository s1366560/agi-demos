# Test Organization Standard

**Feature**: Test Structure Refactoring and Coverage Enhancement
**Version**: 1.0.0
**Date**: 2026-01-04

## Purpose

This document defines the standard organization and structure for all tests in the MemStack codebase to ensure consistency, maintainability, and alignment with hexagonal architecture principles.

---

## Principles

### 1. Test Type Separation
Tests MUST be organized by type first (unit, integration, performance, contract) to enable:
- Fast execution of unit tests (<2 seconds)
- Selective test execution based on type
- Clear test intent and scope

### 2. Architectural Alignment
Test directories MUST mirror the hexagonal architecture layers:
- Domain (entities, value objects, domain services)
- Application (use cases, application services)
- Infrastructure (adapters, repositories, routers)

### 3. Discoverability
Test files MUST follow naming conventions that make them easy to find and understand.

### 4. Independence
Each test MUST be independent and not rely on other tests.

---

## Directory Structure

### Backend Tests

```
src/tests/
├── conftest.py                 # Shared fixtures
├── README.md                   # Testing guidelines
│
├── unit/                       # Unit tests (<2s total)
│   ├── domain/
│   │   ├── model/             # Entity tests
│   │   │   ├── test_user.py
│   │   │   ├── test_tenant.py
│   │   │   ├── test_project.py
│   │   │   ├── test_memory.py
│   │   │   └── test_entity.py
│   │   └── services/          # Domain service tests
│   │       └── test_graph_service.py
│   │
│   ├── use_cases/             # Use case tests
│   │   ├── auth/
│   │   │   ├── test_create_api_key.py
│   │   │   ├── test_list_api_keys.py
│   │   │   └── test_delete_api_key.py
│   │   ├── memo/
│   │   │   ├── test_create_memo.py
│   │   │   ├── test_update_memo.py
│   │   │   └── test_delete_memo.py
│   │   ├── memory/
│   │   │   ├── test_create_memory.py
│   │   │   ├── test_update_memory.py
│   │   │   ├── test_delete_memory.py
│   │   │   └── test_search_memory.py
│   │   └── task/
│   │       ├── test_create_task.py
│   │       └── test_update_task.py
│   │
│   ├── services/              # Application service tests
│   │   ├── test_authorization_service.py
│   │   ├── test_memory_service.py
│   │   ├── test_project_service.py
│   │   ├── test_search_service.py
│   │   ├── test_task_service.py
│   │   └── test_tenant_service.py
│   │
│   ├── repositories/          # Repository tests
│   │   ├── test_sql_user_repository.py
│   │   ├── test_sql_tenant_repository.py
│   │   ├── test_sql_project_repository.py
│   │   ├── test_sql_memory_repository.py
│   │   ├── test_sql_memo_repository.py
│   │   └── test_sql_task_repository.py
│   │
│   ├── routers/               # API router tests
│   │   ├── test_auth.py
│   │   ├── test_tenants.py
│   │   ├── test_projects.py
│   │   ├── test_memories.py

│   │   ├── test_tasks.py
│   │   ├── test_episodes.py
│   │   ├── test_recall.py
│   │   └── test_enhanced_search.py
│   │
│   ├── tasks/                 # Background task tests
│   │   ├── test_community_handler.py
│   │   ├── test_deduplicate_handler.py
│   │   └── test_incremental_refresh_handler.py
│   │
│   └── llm/                   # LLM client tests
│       ├── test_qwen_clients.py
│       └── test_gemini_clients.py
│
├── integration/               # Integration tests (real deps)
│   ├── api/                   # API endpoint integration
│   │   ├── test_auth_endpoints.py
│   │   ├── test_tenant_endpoints.py
│   │   ├── test_project_endpoints.py
│   │   ├── test_memory_endpoints.py
│   │   └── test_task_endpoints.py
│   │
│   ├── database/              # Database integration
│   │   ├── test_database_integration.py
│   │   ├── test_repository_integration.py
│   │   └── test_migration_integration.py
│   │
│   ├── graphiti/              # Graphiti integration
│   │   └── test_graphiti_adapter_integration.py
│   │
│   └── security/              # Security integration
│       ├── test_authentication.py
│       ├── test_authorization.py
│       └── test_permission_checks.py
│
├── performance/               # Performance benchmarks
│   ├── test_api_benchmarks.py
│   ├── test_search_benchmarks.py
│   └── test_database_benchmarks.py
│
└── contract/                  # Contract tests
    ├── api/                   # API contract tests
    │   ├── test_memory_api_contract.py
    │   ├── test_project_api_contract.py
    │   └── test_tenant_api_contract.py
    │
    └── adapters/              # Adapter contract tests
        ├── test_repository_contracts.py
        └── test_service_contracts.py
```

### Frontend Tests

```
web/src/test/
├── setup.ts                   # Test setup and mocks
├── utils.tsx                  # Test utilities
│
├── components/                # Component tests
│   ├── test_MemoryDetailModal.tsx
│   ├── test_ProjectManager.tsx
│   ├── test_UserManager.tsx
│   ├── test_EditUserModal.tsx
│   ├── test_ProjectSettingsModal.tsx
│   └── test_TenantLayout.tsx
│
├── pages/                     # Page tests
│   └── test_TenantCreate.tsx
│
├── layouts/                   # Layout tests
│   └── test_TenantLayout.tsx
│
├── stores/                    # Store tests
│   └── (Zustand/Jotai stores)
│
└── services/                  # Service tests
    ├── test_memoryService.ts
    ├── test_projectService.ts
    └── test_tenantService.ts

web/e2e/                       # E2E tests
├── auth.spec.ts
├── memories.spec.ts
├── projects.spec.ts
└── tenants.spec.ts
```

---

## File Naming Conventions

### Backend Files

**Pattern**: `test_<module>_<feature>.py`

**Examples**:
- `test_memory_service.py` - Service layer tests
- `test_create_memory_use_case.py` - Use case tests
- `test_sql_memory_repository.py` - Repository implementation tests
- `test_memories_router.py` - Router tests

**Rules**:
- MUST start with `test_`
- MUST use snake_case
- MUST be descriptive of what is being tested
- MUST match the module being tested

### Frontend Files

**Pattern**: `<ComponentName>.test.tsx` or `<serviceName>.test.ts`

**Examples**:
- `MemoryDetailModal.test.tsx` - Component tests
- `memoryService.test.ts` - Service tests

**Rules**:
- MUST end with `.test.tsx` (components) or `.test.ts` (services)
- MUST use PascalCase for components
- MUST use camelCase for services
- MUST match the file being tested

### E2E Files

**Pattern**: `<feature>.spec.ts`

**Examples**:
- `auth.spec.ts` - Authentication flows
- `member-management.spec.ts` - Member management flows

**Rules**:
- MUST end with `.spec.ts`
- MUST use kebab-case
- MUST describe the user journey being tested

---

## Test File Structure

### Backend Test File Template

```python
"""Tests for <Module> functionality."""

import pytest
from unittest.mock import Mock

# Import the module being tested
from src.application.services.<module> import <Service>


@pytest.mark.unit
class Test<Service>:
    """Test suite for <Service>."""

    async def test_<action>_with_valid_<input>_succeeds(self, test_fixture):
        """Test that <action> succeeds with valid <input>.

        Arrange:
        - Set up test fixtures

        Act:
        - Call the <action> method

        Assert:
        - Verify expected outcome
        """
        # Arrange
        service = <Service>(test_fixture)
        data = {"key": "value"}

        # Act
        result = await service.<action>(data)

        # Assert
        assert result is not None
        assert result.key == "value"

    async def test_<action>_with_invalid_<input>_fails(self, test_fixture):
        """Test that <action> fails with invalid <input>."""
        # ... implementation
```

### Frontend Test File Template

```typescript
/* Tests for <Component> component. */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { <Component> } from '../<Component>';

describe('<Component>', () => {
  it('should render correctly with required props', () => {
    // Arrange
    const props = {
      prop1: 'value1',
      prop2: 'value2',
    };

    // Act
    render(<<Component> {...props} />);

    // Assert
    expect(screen.getByText('expected text')).toBeInTheDocument();
  });

  it('should handle user interaction', async () => {
    // Arrange
    const user = userEvent.setup();
    const mockHandler = vi.fn();

    // Act
    render(<<Component> onClick={mockHandler} />);
    await user.click(screen.getByRole('button'));

    // Assert
    expect(mockHandler).toHaveBeenCalledOnce();
  });
});
```

---

## Test Markers

### Backend Markers

```python
@pytest.mark.unit           # Unit test (fast, mocked)
@pytest.mark.integration    # Integration test (real deps)
@pytest.mark.slow           # Slow test (>1s execution)
@pytest.mark.performance    # Performance benchmark
@pytest.mark.contract       # Contract test
@pytest.mark.security       # Security test
```

**Usage**:
```python
@pytest.mark.unit
class TestMemoryService:
    @pytest.mark.slow
    async def test_large_operation(self):
        # This is a slow unit test
        pass
```

**Running by marker**:
```bash
pytest -m unit              # Run only unit tests
pytest -m "not slow"        # Run all except slow tests
pytest -m "integration and security"  # Run security integration tests
```

---

## Import Standards

### Backend Imports

**Order**:
1. Standard library imports
2. Third-party imports (pytest, etc.)
3. Application imports (src/)
4. Relative imports (same package)

**Example**:
```python
"""Tests for memory service."""

import uuid
from datetime import datetime
from unittest.mock import Mock, AsyncMock

import pytest
from httpx import AsyncClient

from src.application.services.memory_service import MemoryService
from src.domain.model.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepositoryPort
```

### Frontend Imports

**Order**:
1. Vitest imports
2. React imports
3. Testing library imports
4. Component being tested
5. Other components

**Example**:
```typescript
/* Tests for UserManager component. */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { UserManager } from '../components/UserManager';
import { projectService } from '../services/projectService';
```

---

## Fixture Standards

### Fixture Placement

**Rule**: Fixtures MUST be in `conftest.py` closest to where they're used

**Priority**:
1. `src/tests/conftest.py` - Global fixtures (database, mocks)
2. `src/tests/unit/conftest.py` - Unit test fixtures
3. `src/tests/integration/conftest.py` - Integration test fixtures

### Fixture Naming

**Pattern**: `<resource>_<scope>`

**Examples**:
- `test_db` - Function-scoped database session
- `test_user` - Sample user entity
- `mock_graphiti_client` - Mocked Graphiti client

### Fixture Documentation

**Rule**: All fixtures MUST have docstrings

**Example**:
```python
@pytest.fixture
async def test_db(test_engine):
    """Create an async database session for testing.

    The session is wrapped in a transaction that is rolled back
    after each test to ensure test isolation.

    Yields:
        AsyncSession: Database session with test data
    """
    async with test_engine.begin() as conn:
        async_session = AsyncSession(test_engine, expire_on_commit=False)
        yield async_session
        await async_session.rollback()
```

---

## Coverage Standards

### Target Coverage

| Layer | Target | Rationale |
|-------|--------|-----------|
| Domain | 90% | Critical business logic |
| Application | 80% | Use cases and orchestration |
| Infrastructure | 60% | Mostly integration tests |

### Coverage Exclusions

**File**: `.coveragerc`

```ini
[omit]
# External dependencies
*/venv/*
*/env/*
*/.venv/*

# Test files
*/tests/*
*/test_*

# Generated code
*/__generated__/*

# LLM clients (external dependencies)
*/llm/*

# Debug utilities
*/debug_utils.py

# Exceptions (simple classes)
*/exceptions/*
```

### Coverage Reporting

**Generate coverage**:
```bash
# HTML report
make test-coverage

# Terminal report
pytest --cov=src --cov-report=term-missing

# Combined report
pytest --cov=src --cov-report=html --cov-report=term
```

**Review coverage**:
- Open `htmlcov/index.html` in browser
- Look for red lines (uncovered code)
- Prioritize covering domain and application layers

---

## Quality Standards

### Test Independence

**Requirement**: Each test MUST be independent

**Rules**:
- Tests MUST NOT depend on execution order
- Tests MUST NOT share state
- Each test MUST setup and teardown its own data

**Verification**:
```bash
# Run tests in random order
pytest --random-order

# Run tests multiple times
pytest --count=5
```

### Test Determinism

**Requirement**: Tests MUST produce same results on every run

**Rules**:
- No random data in assertions
- No time-dependent assertions without mocking
- No sleep statements (use async/await)

### Test Clarity

**Requirement**: Tests MUST be easy to understand

**Rules**:
- Follow Arrange-Act-Assert pattern
- Use descriptive test names
- Add comments for complex setup
- Test one thing only

### Test Maintainability

**Requirement**: Tests MUST be easy to maintain

**Rules**:
- Use fixtures for shared setup
- Avoid duplication
- Keep tests simple
- Update tests with code changes

---

## Migration Checklist

When migrating tests from legacy structure:

- [ ] Identify test type (unit/integration)
- [ ] Identify architectural layer
- [ ] Move file to appropriate directory
- [ ] Update imports to use absolute paths
- [ ] Verify test still passes
- [ ] Update pytest.ini if needed
- [ ] Remove old file after verification
- [ ] Update documentation

---

## Compliance

All tests in the codebase MUST comply with this standard. Non-compliant tests SHOULD be refactored during code reviews.

**Version**: 1.0.0
**Last Updated**: 2026-01-04
