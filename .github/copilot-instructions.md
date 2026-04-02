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

## Design Context

### Users

Enterprise developers and technical professionals who use AI agents as collaborative partners. They work with complex multi-layer agent systems (Tool -> Skill -> SubAgent -> Agent) and need to:
- Monitor agent reasoning and execution
- Manage knowledge graphs and memories
- Configure and orchestrate specialized subagents
- Review artifacts and execution traces

### Brand Personality

**Clean, Minimal, Technical**

Vercel-inspired aesthetic: black/white/gray palette, function-first, zero visual noise. Every pixel serves a purpose.

- **Confidence & Precision**: Crisp typography, tight spacing, no decorative elements
- **Voice**: Direct, technical, efficient - every word earns its place
- **Tone**: Calm competence, understated authority

### Aesthetic Direction

**Vercel Design Language** - extracted from vercel.com

- **Monochrome Foundation**: Black `#000`/`#171717` text on white `#fff`/`#fafafa` backgrounds
- **10-Level Gray Scale**: `#111` to `#fafafa` (accents-1 through accents-8 + foreground/background)
- **Blue Accent**: `#0070f3` (success/link color), used sparingly for CTAs
- **Geist Typography**: Tight negative letter-spacing on headings (-2.4px at 48px)
- **NOT playful/consumer apps**: No decorative blurs, gradients, or gamification
- **NOT cluttered enterprise**: No dense dashboards with competing widgets

### Design Principles

1. **Clarity Over Cleanness**: Information hierarchy first. Tight negative letter-spacing on headings for max legibility
2. **Zero Visual Noise**: 1px borders, 0.08 alpha shadows, solid backgrounds. Every element must convey information
3. **Pill-Shape CTAs**: Primary buttons use pill shape (radius: 100px, height: 48px). Secondary: white bg, dark text, same shape
4. **Progressive Disclosure**: Essential info first. Status badges: 11px/500 pill shape. Complex details on demand
5. **Consistent Component Language**: 6px default radius, 8px marketing radius, 4px spacing base, border-only shadows

### Component Patterns

#### Primary Button (CTA)
- bg `#171717`, text `#fff` 16px/500, radius 100px, height 48px

#### Secondary Button
- bg `#fff`, text `#171717` 16px/500, radius 100px, height 48px

#### Ghost Button (Nav)
- transparent bg, text `#4d4d4d` 14px/400, radius 9999px, height 30px

#### Input Field
- bg `#fff`, no border (container provides it), radius 6px, height 40px, font 14px

#### Badge/Tag
- bg `#ebebeb`, text `#171717` 11px/500, radius 9999px, padding 0 8px

#### Card
- bg `#fff`, radius 6px, shadow `0 0 0 1px rgba(0,0,0,0.08)` + subtle inner

### Color Tokens (Light Mode)

```css
/* Gray scale */
--accents-1: #fafafa   /* lightest bg */
--accents-2: #eaeaea   /* borders */
--accents-3: #999999   /* muted text */
--accents-5: #666666   /* secondary text */
--accents-7: #333333   /* emphasized */
--accents-8: #111111   /* near-black */
--foreground: #000000  /* primary text */
--background: #ffffff  /* page bg */

/* Semantic */
--primary: #0070f3     /* links, active states */
--error: #ee0000
--warning: #f5a623
```

### Spacing & Radius

```
4px base: 4, 8, 12, 16, 24, 32, 40, 64, 96
Default radius: 6px (inputs, cards)
Marketing radius: 8px
Pill radius: 100px (CTAs) / 9999px (badges)
```

### Shadows (Minimal)

```css
--shadow-border: 0 0 0 1px rgba(0,0,0,0.08)
--shadow-small: 0 2px 2px rgba(0,0,0,0.04)
--shadow-menu: border + 0 4px 8px rgba(0,0,0,0.04), 0 16px 24px rgba(0,0,0,0.06)
```

### Accessibility

Target: WCAG 2.1 AA compliance. Focus ring: `0 0 0 1px gray + 0 0 0 4px rgba(0,0,0,0.16)`. All animations respect `prefers-reduced-motion`.
