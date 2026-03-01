# src/tests/

Backend test suite. SQLite in-memory for unit tests, real services for integration.

## Directory Structure

| Dir | Purpose | Speed |
|-----|---------|-------|
| `unit/` | Mocked dependencies, no real DB/services | <2s total |
| `integration/` | Real DB, real Redis, real Neo4j | Slower |
| `contract/` | API contract tests (request/response shape validation) | Medium |
| `performance/` | Benchmark tests (API, search, DB) | Slowest |
| `infrastructure/` | Infrastructure-specific tests | Medium |
| `conftest.py` | Shared fixtures (800+ lines) | -- |

## Unit Test Layout (mirrors hexagonal architecture)

```
unit/
  domain/model/       -- Entity/value object tests
  use_cases/           -- Use case tests (auth/, memo/, memory/, task/)
  services/            -- Application service tests
  repositories/        -- Repository implementation tests (SQLite)
  routers/             -- API router tests (TestClient)
  tasks/               -- Background task handler tests
  llm/                 -- LLM client tests (litellm/)
```

## Key Fixtures (conftest.py)

| Fixture | Scope | Provides |
|---------|-------|----------|
| `test_engine` | function | SQLite in-memory engine with all tables created |
| `test_db` / `db_session` / `db` | function | AsyncSession (auto-rollback after test) |
| `test_user` | function | DB User model (id=`TEST_USER_ID`) |
| `another_user` | function | Second user for multi-user scenarios |
| `test_domain_user` | function | Domain User model (no DB) |
| `test_tenant_db` | function | Tenant with UserTenant membership |
| `test_project_db` | function | Project with UserProject (owner role) |
| `test_memory_db` | function | Memory in test project |
| `authenticated_client` | function | TestClient with auth headers |

## Constants (conftest.py)

- `TEST_USER_ID` = `550e8400-e29b-41d4-a716-446655440000`
- `TEST_TENANT_ID` = `...440001`, `TEST_PROJECT_ID` = `...440002`, `TEST_MEMORY_ID` = `...440003`

## Running Tests

```bash
uv run pytest src/tests/ -m "unit" -v          # Unit only
uv run pytest src/tests/ -m "integration" -v   # Integration only
uv run pytest src/tests/unit/test_file.py -v   # Single file
uv run pytest src/tests/unit/test_file.py::TestClass::test_method -v  # Single test
```

## Conventions

- `asyncio_mode = "auto"` in pytest.ini -- no `@pytest.mark.asyncio` needed
- Mark classes: `@pytest.mark.unit`, `@pytest.mark.integration`
- Test naming: `test_{action}_{scenario}_{expected}` (e.g. `test_create_with_empty_name_fails`)
- Arrange-Act-Assert pattern. One assertion focus per test
- Fixtures chain: `test_user` -> `test_tenant_db` -> `test_project_db` -> `test_memory_db`
- Coverage target: 80%+ overall, 90% domain, 80% application, 60% infrastructure

## Forbidden

- Never depend on test execution order
- Never use `time.sleep()` -- use async/await
- Never share mutable state between tests
- Never skip rollback in fixtures (causes test pollution)
