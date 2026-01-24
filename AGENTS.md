# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with code in this repository.

## Repository Overview

MemStack is an Enterprise AI Memory Cloud Platform - a full-stack Python backend service with React frontend. The backend follows **Domain Driven Design (DDD)** and **Hexagonal Architecture** patterns.

## Key Files

- `CLAUDE.md` - Detailed development commands and architecture documentation
- `README.md` - Project overview and setup instructions
- `src/tests/README.md` - Testing organization standards
- `domain_driven_design_hexagonal_arhictecture_python_rules.md` - Architecture guidelines for DDD + Hexagonal patterns

## Development Commands

### Quick Start (Environment Setup & Reset)

```bash
# First time setup - installs deps, starts infra, initializes database
make init

# Start development (after init)
make dev              # Start backend services (API + worker + infra)
make dev-web          # Start frontend in another terminal

# Quick restart services
make restart

# Complete reset - stops services, cleans Docker volumes, prepares for reinit
make reset

# Fresh start from zero (reset + init + dev)
make fresh

# Reset only database (keep Docker volumes)
make reset-db

# Check service status
make status
```

### Common Development Commands

```bash
# Setup & Installation
make install              # Install all dependencies (backend + web)

# Running Services
make dev                  # Start all backend services (API + worker + infra)
make dev-stop             # Stop all background services
make dev-web              # Start frontend development server

# Testing
make test                 # Run all tests
make test-unit            # Unit tests only (fast)
make test-integration     # Integration tests only
make test-coverage        # Run with coverage report (80%+ target)

# Code Quality
make format               # Format all code (ruff format + lint fix)
make lint                 # Lint all code
make check                # Run format + lint + test

# Database
make db-init              # Initialize database
make db-reset             # Reset database (WARNING: deletes all data)
```

## Running Single Tests

```bash
# Run specific test file
uv run pytest src/tests/unit/test_memory_service.py -v

# Run tests by marker
uv run pytest src/tests/ -m "unit" -v
uv run pytest src/tests/ -m "integration" -v

# Run single test function
uv run pytest src/tests/unit/test_memory_service.py::TestMemoryService::test_create_memory_success -v
```

## API Testing with curl

### Getting API Key

After `make init`, the system creates default users with API keys. Check the startup logs for keys:
```bash
tail -50 logs/api.log | grep "API Key"
# Output: 🔑 Default Admin API Key created: ms_sk_xxx...
```

Or login to get a token:
```bash
# Login to get API key
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@memstack.ai&password=adminpassword"
# Returns: {"access_token": "ms_sk_...", "token_type": "bearer"}
```

### API Key Format
- Format: `ms_sk_` + 64 hex characters
- Example: `ms_sk_a1b2c3d4e5f6...`
- Stored as SHA256 hash in database (never plain text)

### Using API Key in Requests

```bash
# Set your API key (from login or logs)
export API_KEY="ms_sk_your_key_here"

# List projects
curl -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/api/v1/projects

# Create an episode
curl -X POST http://localhost:8000/api/v1/episodes \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "1", "content": "Test episode content"}'

# Agent chat (SSE streaming)
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "conv-id", "message": "Hello", "project_id": "1"}'
```

### Default Test Credentials
| User | Email | Password | Role |
|------|-------|----------|------|
| Admin | `admin@memstack.ai` | `adminpassword` | admin |
| User | `user@memstack.ai` | `userpassword` | user |

### API Documentation
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Architecture & Project Structure

```
src/
├── domain/               # Core business logic (no external dependencies)
│   ├── model/           # Entities, value objects, aggregates
│   ├── ports/           # Repository interfaces and domain service ports
│   └── events/          # Domain events
├── application/          # Application orchestration layer
│   ├── ports/           # Primary (use cases) and secondary ports
│   ├── services/        # Application services
│   └── use_cases/       # Use case implementations
├── infrastructure/      # External implementations (adapters)
│   └── adapters/
│       ├── primary/      # Web controllers, CLI
│       └── secondary/    # Repositories, external APIs
└── configuration/       # Settings and DI container

src/tests/               # All tests (unit, integration, contract, performance)
├── unit/                # Fast unit tests with mocks
├── integration/         # Tests with real dependencies
├── contract/            # Contract tests
└── performance/         # Performance benchmarks
```

## Code Style Guidelines

### Python (Backend)

**Formatting & Linting:**
- Line length: 100 characters
- Use `ruff` for formatting and linting (configured in pyproject.toml)
- Type checking with `mypy` (optional, permissive config)

**Import Order:**
1. Standard library imports
2. Third-party imports (pytest, fastapi, etc.)
3. Application imports (src/)
4. Relative imports (same package)

**Naming Conventions:**
- Classes: `PascalCase` (e.g., `UserService`, `SqlUserRepository`)
- Functions/variables: `snake_case` (e.g., `create_user`, `user_id`)
- Private: `_leading_underscore`
- Constants: `UPPER_SNAKE_CASE`

**Domain Models:**
- Use `@dataclass(kw_only=True)` for entities
- Use `@dataclass(frozen=True)` for value objects
- Include validation in `__post_init__` methods
- Domain exceptions inherit from base `DomainException`

**Repository Pattern:**
- Define interfaces in `domain/ports/repositories/`
- Implement in `infrastructure/adapters/secondary/persistence/`
- Use async methods: `async def save(self, entity: Entity) -> None:`
- Return domain objects, not database models

**Testing:**
- Use `@pytest.mark.unit` for unit tests
- Use `@pytest.mark.integration` for integration tests
- Tests use `asyncio_mode = "auto"` - no need for `@pytest.mark.asyncio`
- Follow Arrange-Act-Assert pattern
- Fixtures in `conftest.py` closest to usage

### TypeScript (Frontend)

**Formatting & Linting:**
- Use `eslint` with TypeScript plugin
- `no-unused-vars` as warning (allow `_` prefix)
- `@typescript-eslint/no-explicit-any` disabled
- Path mapping: `@/*` → `src/*`

**Naming Conventions:**
- Components: `PascalCase` (e.g., `MemoryDetailModal`)
- Functions/variables: `camelCase` (e.g., `fetchUserData`)
- Files: `PascalCase.tsx` for components, `camelCase.ts` for utilities

**Test Files:**
- Unit tests: `<ComponentName>.test.tsx`
- Service tests: `<serviceName>.test.ts`
- E2E tests: `<feature>.spec.ts`

## Error Handling

**Backend:**
- Domain exceptions in `domain/exceptions/`
- Use specific exception types (e.g., `UserNotFoundError`, `InvalidEmailError`)
- Infrastructure adapters catch external errors and raise domain exceptions
- HTTP controllers map domain exceptions to appropriate status codes

**Frontend:**
- Use React error boundaries for component errors
- API errors handled in service layer
- User-facing error messages through i18n

## Testing Strategy

**Unit Tests:**
- Target: Domain (90%), Application (80%), Infrastructure (60%)
- Mock all external dependencies
- Focus on business logic invariants

**Integration Tests:**
- Test repository implementations with real database
- Test API endpoints with full request/response cycle
- Use test database with transaction rollback

**Markers:**
- `@pytest.mark.unit` - Fast tests with mocks
- `@pytest.mark.integration` - Real dependencies
- `@pytest.mark.slow` - Tests taking >1 second
- `@pytest.mark.performance` - Performance benchmarks

## Key Technologies

- **Backend:** Python 3.12+, FastAPI 0.110+, SQLAlchemy 2.0+, PostgreSQL 16+, Redis 7+, Neo4j 5.26+
- **Frontend:** TypeScript 5.9+, React 19.2+, Vite 7.3+, Ant Design 6.1+, Zustand 5.0+
- **Agent Framework:** Self-developed ReAct Core, LangChain 0.3+ (for LLM utilities)
- **Knowledge Graph:** Native Graph Adapter (自研知识图谱引擎)
- **LLM Providers:** LiteLLM 1.0+ supporting:
  - Google Gemini (default for entity extraction)
  - Alibaba Qwen (Chinese language optimization)
  - Deepseek (cost-effective reasoning)
  - ZhipuAI (Chinese language)
  - OpenAI (GPT models)
- **Testing:** pytest 9.0+ (backend), Vitest 4.0+ + Playwright 1.57+ (frontend)
- **Infrastructure:** Docker, uv package manager

## Development Workflow

1. Run `make install` for initial setup
2. Use `make dev` to start all services
3. Make changes following DDD + Hexagonal patterns
4. Run `make check` before committing
5. Focus on domain-first development

## Core Domain Concepts

**Episodes**: Discrete interactions/events containing content and metadata. Processed asynchronously to extract knowledge.

**Memories**: Semantic memory derived from episodes - facts, relationships stored in Neo4j knowledge graph.

**Entities**: Real-world objects (people, organizations, concepts) with attributes and relationships.

**Projects**: Multi-tenant isolation units. Each project has its own knowledge graph.

**React Agent System**: Multi-level thinking AI agent with self-developed ReAct Core:
- **Conversations**: Multi-turn chat sessions
- **Work Plans**: Work-level planning with sequential steps
- **Plan Steps**: Task-level execution with reasoning
- **Workflow Patterns**: Learned patterns from successful executions (tenant-scoped)
- **Agent Tools**: MemorySearch, EntityLookup, GraphQuery, MemoryCreate, EpisodeRetrieval, Summary, WebSearch, WebScrape, Clarification, Decision
- **SSE Streaming**: Real-time responses via Server-Sent Events
- **Permission Control**: Fine-grained tool permission (allow/deny/ask)
- **Doom Loop Detection**: Automatic detection and intervention for stuck agents
- **Cost Tracking**: Real-time token and cost calculation (50+ models supported)

## Key File Locations

### Backend Entry Points
- API: `src/infrastructure/adapters/primary/web/main.py`
- Worker: `src/worker.py`
- Config: `src/configuration/config.py`
- DI Container: `src/configuration/di_container.py`

### Agent System
- ReAct Agent Core: `src/infrastructure/agent/core/react_agent.py`
- Session Processor: `src/infrastructure/agent/core/processor.py`
- LLM Stream: `src/infrastructure/agent/core/llm_stream.py`
- Permission Manager: `src/infrastructure/agent/permission/manager.py`
- Cost Tracker: `src/infrastructure/agent/cost/tracker.py`
- Agent Tools: `src/infrastructure/agent/tools/`
- Agent Use Cases: `src/application/use_cases/agent/`
- Agent Domain Models: `src/domain/model/agent/`
- Agent Router: `src/infrastructure/adapters/primary/web/routers/agent.py`

### Knowledge Graph System
- Native Graph Adapter: `src/infrastructure/graph/native_graph_adapter.py`
- Entity Extractor: `src/infrastructure/graph/extraction/entity_extractor.py`
- Relationship Extractor: `src/infrastructure/graph/extraction/relationship_extractor.py`
- Hybrid Search: `src/infrastructure/graph/search/hybrid_search.py`
- Community Updater: `src/infrastructure/graph/community/community_updater.py`
- Graph Service Port: `src/domain/ports/services/graph_service.py`

### Frontend
- Agent Chat Page: `web/src/pages/project/AgentChat.tsx`
- Agent Store: `web/src/stores/agent.ts`
- Agent Service: `web/src/services/agentService.ts`
- Chat Interface: `web/src/components/agent/ChatInterface.tsx`

## Database Operations

### Alembic Migration Guidelines

**Critical Rules:**
1. **NEVER modify database directly** - Always use Alembic migrations
2. **Always use `--autogenerate`** for schema changes:
   ```bash
   # 1. Modify SQLAlchemy models in src/infrastructure/adapters/secondary/persistence/models.py
   # 2. Generate migration
   PYTHONPATH=. uv run alembic revision --autogenerate -m "description"
   # 3. Review and edit the generated migration
   # 4. Test migration
   PYTHONPATH=. uv run alembic upgrade head
   ```
3. **Review autogenerated migrations** - May include false positives or miss operations

**Migration Commands:**
```bash
PYTHONPATH=. uv run alembic current                    # Show current revision
PYTHONPATH=. uv run alembic history                    # Show migration history
PYTHONPATH=. uv run alembic upgrade head               # Apply all migrations
PYTHONPATH=. uv run alembic downgrade -1               # Rollback one migration
```

**Naming Convention:**
- Use descriptive, lowercase names: `add_user_preferences_table`
- Feature-specific prefixes: `agent_*`, `billing_*`, `schema_*`, `litellm_*`

### Database Schema

**PostgreSQL** (metadata):
- `users`, `tenants`, `projects` - Multi-tenant structure
- `api_keys` - Authentication (SHA256 hashed, format: `ms_sk_` + 64 hex chars)
- `episodes` - Episode metadata and content
- `conversations`, `messages`, `work_plans`, `plan_steps` - Agent system
- `llm_provider_configs` - LLM provider settings

**Neo4j** (knowledge graph):
- Nodes: Entities with attributes
- Relationships: Typed edges with weights
- Temporal: `created_at`, `valid_at` timestamps for historical queries

**Redis** (cache):
- Session data, frequently accessed queries

## Important Notes

- **Multi-tenancy**: Always scope queries by `project_id` or `tenant_id`
- **Async I/O**: All database/HTTP operations must be async
- **API Key format**: `ms_sk_` + 64 hex chars, stored as SHA256 hash
- Database auto-initializes on first `make dev` run
- Migrations auto-run on application startup via lifespan hook
- Worker service handles async tasks (episode processing, indexing)
- All logs in `logs/` directory
- Use absolute imports from `src/` root
- Follow hexagonal architecture: Ports define contracts, Adapters implement technology
- **Neo4j is critical**: Core knowledge graph functionality requires Neo4j 5.26+
- **Agent state**: Agent conversations are stateful; use conversation_id for continuity
- **Test coverage**: Must maintain 80%+ overall coverage