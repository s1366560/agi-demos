<!--
SYNC IMPACT REPORT
==================
Version Change: [TEMPLATE] → 1.0.0
Rationale: Initial constitution ratification with 4 core principles

Principles Added:
- I. Code Quality (Hexagonal Architecture & Clean Code)
- II. Testing Standards (Test-First & Coverage Requirements)
- III. User Experience Consistency (API & Interface Design)
- IV. Performance Requirements (Response Times & Resource Limits)

Templates Status:
✅ .specify/templates/plan-template.md - Reviewed, Constitution Check section aligns
✅ .specify/templates/spec-template.md - Reviewed, requirements structure compatible
✅ .specify/templates/tasks-template.md - Reviewed, task organization supports principles
✅ .specify/templates/agent-file-template.md - Reviewed
✅ .specify/templates/checklist-template.md - Reviewed

Follow-up TODOs: None

Last Updated: 2026-01-04
-->

# MemStack Constitution

## Core Principles

### I. Code Quality (Hexagonal Architecture & Clean Code)

**Non-Negotiable Rules:**

- Domain Layer MUST remain independent of all infrastructure concerns - no imports from FastAPI, database drivers, or external frameworks allowed in `src/domain/`
- All external dependencies MUST be abstracted through ports (interfaces) in `src/domain/ports/` and implemented by adapters in `src/infrastructure/adapters/`
- Business logic MUST reside in domain services and entities - application layer coordinates only, it does not contain business rules
- Repository pattern MUST be used for all data access - domain defines repository interfaces, infrastructure provides implementations
- Dependency injection MUST be handled through the container in `src/configuration/container.py` - no hardcoded dependencies or service locators
- Code MUST follow PEP 8 style guidelines - use Ruff for formatting and linting before committing
- Type hints MUST be used on all public functions and class methods - run MyPy type checking before commits
- Functions MUST be kept under 50 lines - if longer, refactor into smaller, named helper functions
- Cyclomatic complexity MUST not exceed 10 per function - use extraction and simplification to reduce complexity
- ALL public APIs MUST have docstrings - follow Google docstring format with clear descriptions, args, and returns

**Rationale:** Hexagonal architecture ensures the domain remains testable and decoupled from infrastructure changes. Clean code practices maintain long-term maintainability and reduce cognitive load for developers working across the codebase.

---

### II. Testing Standards (Test-First & Coverage Requirements)

**Non-Negotiable Rules:**

- Test-First Development (TDD) is MANDATORY for all new features - write failing tests, get approval, then implement
- Test Coverage MUST be maintained at 80% or higher - check with `make test` before pushing
- Three test layers MUST be used appropriately:
  - **Unit Tests**: Test domain logic in isolation (no external dependencies) in `src/tests/unit/`
  - **Integration Tests**: Test adapter/port contracts with real dependencies in `src/tests/integration/`
  - **Contract Tests**: Test API boundaries and protocol compliance in `src/tests/contract/`
- Unit tests MUST run in under 2 seconds total - use mocks for external services
- Integration tests MUST use test containers for Neo4j, PostgreSQL, and Redis - no external service dependencies
- Tests MUST be deterministic - no random data, sleeps, or time-dependent assertions without proper mocking
- Each test MUST follow the Arrange-Act-Assert pattern with clear section comments
- Tests MUST be independent - no shared state between tests, must run successfully in any order
- All edge cases and error paths MUST have explicit test coverage - not just happy paths

**Rationale:** High test coverage prevents regressions, enables confident refactoring, and serves as living documentation. TDD ensures testable design and better APIs. The three-layer testing strategy provides fast feedback while validating system behavior at multiple levels.

---

### III. User Experience Consistency (API & Interface Design)

**Non-Negotiable Rules:**

- All API endpoints MUST follow RESTful conventions - use appropriate HTTP verbs (GET, POST, PUT, DELETE), resource-based URLs, and status codes
- API responses MUST use consistent structure - wrap responses in `{ "data": ..., "meta": ... }` for data endpoints
- Error responses MUST include machine-readable error codes and human-readable messages - format: `{ "error": { "code": "ERROR_CODE", "message": "...", "details": {} } }`
- All endpoints MUST require authentication via API Key in `Authorization: Bearer ms_sk_...` header - except documented public endpoints (e.g., `/health`)
- API versioning MUST use URL path versioning (e.g., `/api/v1/`, `/api/v2/`) - breaking changes require new major version
- Request validation MUST provide clear, field-level error messages - include field name and specific validation failure
- Web UI MUST follow Ant Design component library patterns - consistent styling, interactions, and responsive behavior
- Loading states MUST be displayed for all async operations - show spinners or skeleton screens during API calls
- User-facing error messages MUST be actionable - explain what went wrong and how to fix it (no generic "error occurred")
- Pagination MUST be used for all list endpoints returning 10+ items - default page size 20, max 100, return total count

**Rationale:** Consistent APIs reduce integration friction and improve developer experience. Predictable patterns enable faster onboarding and fewer support requests. Actionable error messages turn frustrations into self-service resolutions.

---

### IV. Performance Requirements (Response Times & Resource Limits)

**Non-Negotiable Rules:**

- API response times:
  - P95 (95th percentile) latency for simple CRUD operations MUST be under 200ms
  - P95 latency for search/memory retrieval operations MUST be under 500ms
  - P95 latency for episode ingestion with graph extraction MUST be under 2s
  - Health check endpoint MUST respond in under 50ms
- Memory usage:
  - API server processes MUST NOT exceed 512MB RSS under normal load
  - Memory leaks MUST be addressed within 1 week of detection
- Database query efficiency:
  - Neo4j queries MUST use indexed properties where available - monitor slow query logs
  - PostgreSQL queries MUST be EXPLAIN ANALYZED before merge - ensure index usage
  - No N+1 queries allowed - use batching and proper JOIN patterns
- Background job processing:
  - SSE (Server-Sent Events) streams MUST emit progress updates at least every 5 seconds
  - Background tasks MUST timeout after 5 minutes and report failure
- Caching strategy:
  - Embeddings and frequently accessed data MUST be cached in Redis with TTL
  - Cache keys MUST follow naming pattern: `{resource}:{id}:{version}` - e.g., `memory:123:v1`
- Concurrency handling:
  - API MUST support 100 concurrent requests without degradation
  - Database connection pools MUST be sized appropriately (typically 10-20 connections per worker)

**Rationale:** Performance is a feature. Slow APIs erode user trust and increase infrastructure costs. Clear benchmarks prevent performance regression and ensure scalability as the user base grows.

---

## Architecture & Technology Standards

### Hexagonal Architecture Layers

```
src/
├── domain/                 # Core business logic (no external dependencies)
│   ├── model/             # Entities and value objects
│   ├── ports/             # Interfaces for external interactions
│   └── services/          # Domain services with business rules
├── application/           # Use cases and orchestration
│   └── services/          # Application services (coordinate domain)
├── infrastructure/        # External concerns implementation
│   └── adapters/          # Port implementations (database, API, LLM)
└── configuration/         # DI container and wiring
```

### Technology Stack Requirements

- **Language**: Python 3.12+
- **Web Framework**: FastAPI 0.110+ for all HTTP endpoints
- **Graph Database**: Neo4j 5.26+ for knowledge graph storage
- **Relational Database**: PostgreSQL 16+ for metadata (optional)
- **Caching**: Redis 7+ for caching and session management
- **LLM Providers**: Google Gemini OR Alibaba Qwen (configured via `LLM_PROVIDER`)
- **Testing**: pytest for all test layers, pytest-asyncio for async tests
- **Code Quality**: Ruff (formatting + linting), MyPy (type checking)
- **API Documentation**: OpenAPI 3.0 via FastAPI auto-generated docs at `/docs`

### Dependency Management

- Use `uv` for fast dependency resolution and installation
- All dependencies MUST be pinned to exact versions in `pyproject.toml`
- Development dependencies MUST be organized in `[dev]`, `[test]`, `[neo4j]` extras
- Security vulnerabilities MUST be patched within 7 days of advisory

---

## Development Workflow

### Before Committing

1. Run `make format` - applies Ruff formatting
2. Run `make lint` - passes Ruff linting with zero errors
3. Run `make test` - passes all tests with 80%+ coverage
4. Run `npx tsc` (if web changes) - passes TypeScript type checking

### Pull Request Requirements

- PR title MUST follow conventional commit format: `type(scope): description`
  - Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`
- PR description MUST include:
  - Summary of changes (2-3 sentences)
  - Link to related issue or spec document
  - Testing approach (how changes were validated)
  - Breaking changes documentation (if applicable)
- All checks MUST pass: CI/CD pipeline, security scans, code coverage
- At least one approval MUST be received from maintainers

### Code Review Standards

- Reviewers MUST verify compliance with all constitution principles
- Security concerns MUST block merge until addressed
- Performance violations MUST have explicit justification or remediation plan
- Test coverage regressions MUST be corrected before merge

---

## Governance

### Amendment Process

1. Propose constitutional changes via issue with "Constitution Amendment" label
2. Discuss implications and document rationale
3. Update version number according to semantic versioning:
   - MAJOR: Remove or redefine core principles (backward-incompatible)
   - MINOR: Add new principles or sections (backward-compatible)
   - PATCH: Clarify wording, fix typos, non-semantic changes
4. Update all dependent templates (plan, spec, tasks)
5. Announce changes to team with migration guide if needed

### Compliance Review

- All code reviews MUST verify constitutional compliance
- Violations MUST be documented with justification or remediation
- Technical debt MUST be tracked with explicit payoff criteria
- Monthly compliance audit: sample 5 recent PRs for adherence

### Complexity Justification

- Architecture complexity MUST be justified by clear problem requirements
- Simpler alternatives MUST be documented and explained if rejected
- Over-engineering is a violation of the Code Quality principle

---

**Version**: 1.0.0 | **Ratified**: 2025-12-19 | **Last Amended**: 2026-01-04
