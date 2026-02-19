# Copilot Instructions for MemStack

MemStack is an Enterprise AI Memory Cloud Platform with a Python backend (FastAPI) and React frontend, following **DDD + Hexagonal Architecture**.

## Commands

### Development
```bash
make init          # First-time setup (install deps + start infra + init DB)
make dev           # Start all backend services (API + workers)
make dev-web       # Start frontend (separate terminal)
make status        # Check service status
make dev-stop      # Stop all services
```

### Testing
```bash
make test                    # Run all tests
make test-unit               # Unit tests only (fast)
make test-integration        # Integration tests only
make test-coverage           # With coverage report (80%+ target)

# Single test file
uv run pytest src/tests/unit/test_memory_service.py -v

# Single test function
uv run pytest src/tests/unit/test_memory_service.py::TestMemoryService::test_create_memory_success -v

# By marker
uv run pytest src/tests/ -m "unit" -v
```

### Code Quality
```bash
make format        # Format all code (ruff + eslint)
make lint          # Lint all code
make check         # format + lint + test
```

### Database Migrations
```bash
PYTHONPATH=. uv run alembic revision --autogenerate -m "description"
PYTHONPATH=. uv run alembic upgrade head
PYTHONPATH=. uv run alembic downgrade -1
```

## Architecture

```
src/
├── domain/              # Core business logic (no external deps)
│   ├── model/          # Entities, value objects
│   └── ports/          # Repository/service interfaces
├── application/         # Orchestration layer
│   ├── services/       # Application services
│   └── use_cases/      # Business use cases
├── infrastructure/      # External implementations
│   ├── adapters/
│   │   ├── primary/    # Web API (FastAPI routers)
│   │   └── secondary/  # Repositories, external APIs
│   ├── agent/          # ReAct Agent system
│   ├── llm/            # LiteLLM client
│   └── graph/          # Knowledge graph (Neo4j)
└── configuration/       # Config + DI container

web/src/
├── components/         # React components
├── stores/             # Zustand state management
├── services/           # API clients
└── pages/              # Page components
```

### Key Entry Points
- **API**: `src/infrastructure/adapters/primary/web/main.py`
- **Worker**: `src/worker_temporal.py`
- **Config**: `src/configuration/config.py`
- **DI Container**: `src/configuration/di_container.py`
- **Agent Core**: `src/infrastructure/agent/core/react_agent.py`

## Key Conventions

### Python Backend
- **Line length**: 100 characters, use `ruff` for formatting
- **Async everywhere**: All database/HTTP operations must be async
- **Domain models**: Use `@dataclass(kw_only=True)` for entities, `@dataclass(frozen=True)` for value objects
- **Repository pattern**: Interfaces in `domain/ports/`, implementations in `infrastructure/adapters/secondary/`
- **Multi-tenancy**: Always scope queries by `project_id` or `tenant_id`

### TypeScript Frontend
- **Zustand stores**: When selecting multiple values, use `useShallow` to avoid infinite re-render loops:
  ```tsx
  // ✅ Correct
  import { useShallow } from 'zustand/react/shallow';
  const { value1, value2 } = useStore(useShallow((state) => ({ value1: state.value1, value2: state.value2 })));
  
  // ❌ Wrong - causes infinite loop
  const { value1, value2 } = useStore((state) => ({ value1: state.value1, value2: state.value2 }));
  ```

### Database Migrations
- **Never modify database directly** - always use Alembic migrations
- **Always use `--autogenerate`** then review the generated migration
- Modify models in `src/infrastructure/adapters/secondary/persistence/models.py` first

### Testing
- Use `@pytest.mark.unit` for unit tests, `@pytest.mark.integration` for integration tests
- Tests use `asyncio_mode = "auto"` - no need for `@pytest.mark.asyncio`
- Key fixtures: `db_session`, `test_user`, `test_project_db`, `authenticated_client`

### SSE/Streaming Error Handling
- LLM rate limit errors (429) are retryable - backend emits `retry` events
- Frontend should keep `isStreaming: true` during retries, only stop on fatal errors

## Core Domain Concepts

- **Episodes**: Discrete interactions containing content and metadata
- **Memories**: Semantic memory extracted from episodes, stored in Neo4j
- **Entities**: Real-world objects with attributes and relationships
- **Projects**: Multi-tenant isolation units with independent knowledge graphs
- **API Keys**: Format `ms_sk_` + 64 hex chars, stored as SHA256 hash

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0+, PostgreSQL 16+, Redis 7+, Neo4j 5.26+
- **Workflow**: Temporal.io
- **LLM**: LiteLLM (supports Gemini, Dashscope, Deepseek, OpenAI, Anthropic)
- **Frontend**: React 19+, TypeScript, Vite, Ant Design, Zustand
- **Testing**: pytest, Vitest, Playwright

## Default Credentials (after `make dev`)

- Admin: `admin@memstack.ai` / `adminpassword`
- User: `user@memstack.ai` / `userpassword`

## Service URLs

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- Frontend: http://localhost:3000
- Temporal UI: http://localhost:8080/namespaces/default
