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
│   ├── agent/          # 4-layer Agent system (see below)
│   ├── llm/            # LiteLLM client
│   └── graph/          # Knowledge graph (Neo4j)
└── configuration/       # Config + DI container

Agent 4-Layer Architecture (runs on Ray Actors; entry: src/agent_actor_worker.py)
L4 Agent      ReAct loop: SessionProcessor (Think -> Act -> Observe), DoomLoopDetector, CostTracker
L3 SubAgent   Specialized agents: Orchestrator -> Router (semantic) -> Executor
L2 Skill      Declarative tool compositions with keyword/semantic/hybrid triggers
L1 Tool       Atomic capabilities (Terminal, Desktop, WebSearch/Scrape, Plan, HITL, Sandbox MCP...)
Routing: DIRECT_SKILL -> SUBAGENT -> PLAN_MODE -> REACT_LOOP (confidence-scored).

web/src/
├── components/         # React components
├── stores/             # Zustand state management
├── services/           # API clients
└── pages/              # Page components
```

### Key Entry Points
- **API**: `src/infrastructure/adapters/primary/web/main.py`
- **Config**: `src/configuration/config.py`
- **DI Container**: `src/configuration/di_container.py`
- **Agent Core**: `src/infrastructure/agent/core/react_agent.py`
- **Ray Worker**: `src/agent_actor_worker.py`

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

### Streaming Error Handling (WebSocket transport)
- Agent events stream over WebSocket at `/agent/ws` (migrated off SSE); see `unifiedEventService.ts`
- LLM rate limit errors (429) are retryable - backend emits `retry` events consumed via the `onRetry` handler
- Frontend should keep `isStreaming: true` during retries, only stop on fatal errors

## Core Domain Concepts

- **Episodes**: Discrete interactions containing content and metadata
- **Memories**: Semantic memory extracted from episodes, stored in Neo4j
- **Entities**: Real-world objects with attributes and relationships
- **Projects**: Multi-tenant isolation units with independent knowledge graphs
- **API Keys**: Format `ms_sk_` + 64 hex chars, stored as SHA256 hash

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0+, PostgreSQL 16+, Redis 7+, Neo4j 5.26+
- **Workflow**: asyncio + Ray Actors (dev mode via `make ray-up-dev`)
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

## Design Context

The canonical product/design spec lives in [`PRODUCT.md`](../PRODUCT.md) (Users, Brand Personality, Aesthetic Direction, Design Principles, Component Patterns, color/spacing/shadow tokens, accessibility). Refer to it directly to avoid drift; the summary below is only a quick orientation.

- **Audience**: Enterprise developers orchestrating multi-layer agent systems (Tool -> Skill -> SubAgent -> Agent)
- **Aesthetic**: Vercel-inspired, monochrome (black/white/gray) with a sparing `#0070f3` blue accent, Geist typography
- **Principle**: Clarity and zero visual noise first; pill-shape (radius 100px, height 48px) reserved for explicit CTAs; 4px default control radius / 36px default control height elsewhere
- **Accessibility**: WCAG 2.1 AA; focus ring `0 0 0 1px gray + 0 0 0 4px rgba(0,0,0,0.16)`; respect `prefers-reduced-motion`

---

# GitNexus — Code Intelligence

This project is indexed by GitNexus as **agi-demos**. GitNexus MCP tools are available for code navigation, impact analysis, debugging, and safe refactoring.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **Run impact analysis before editing any symbol.** Before modifying a function, class, or method, use `gitnexus_impact` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **Run `gitnexus_detect_changes` before committing** to verify changes only affect expected symbols and execution flows.
- **Warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query` to find execution flows instead of grepping.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context`.

## Tools Quick Reference

| Tool | When to use |
|------|-------------|
| `gitnexus_query` | Find code by concept ("auth validation") |
| `gitnexus_context` | 360-degree view of one symbol |
| `gitnexus_impact` | Blast radius before editing |
| `gitnexus_detect_changes` | Pre-commit scope check |
| `gitnexus_rename` | Safe multi-file rename |
| `gitnexus_cypher` | Custom graph queries |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/agi-demos/context` | Codebase overview, check index freshness |
| `gitnexus://repo/agi-demos/clusters` | All functional areas |
| `gitnexus://repo/agi-demos/processes` | All execution flows |
| `gitnexus://repo/agi-demos/process/{name}` | Step-by-step execution trace |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Workflow Patterns

### Exploring: "How does X work?"

1. `gitnexus_query({query: "<concept>"})` — find related execution flows
2. `gitnexus_context({name: "<symbol>"})` — deep dive on specific symbol
3. Read `gitnexus://repo/agi-demos/process/{name}` — trace full execution flow

### Impact Analysis: "What breaks if I change X?"

1. `gitnexus_impact({target: "X", direction: "upstream"})` — what depends on this
2. Read `gitnexus://repo/agi-demos/processes` — check affected execution flows
3. `gitnexus_detect_changes()` — map current git changes to affected flows
4. Assess risk and report to user

### Debugging: "Why is X failing?"

1. `gitnexus_query({query: "<error or symptom>"})` — find related execution flows
2. `gitnexus_context({name: "<suspect>"})` — see callers/callees/processes
3. Read `gitnexus://repo/agi-demos/process/{name}` — trace execution flow

### Refactoring: "Rename/extract/split X"

1. `gitnexus_impact({target: "X", direction: "upstream"})` — map all dependents
2. `gitnexus_context({name: "X"})` — see all incoming/outgoing refs
3. For renames: `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first
4. After refactoring: `gitnexus_detect_changes({scope: "all"})` — verify only expected files changed

## Keeping the Index Fresh

After committing code changes, the GitNexus index becomes stale. Re-run:

```bash
npx gitnexus analyze
```

To check whether embeddings exist, inspect `.gitnexus/meta.json`. If `stats.embeddings > 0`, use `npx gitnexus analyze --embeddings` to preserve them.
