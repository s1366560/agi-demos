# MemStack

MemStack is an enterprise AI agent and memory platform. The current codebase combines a
Python/FastAPI backend, a React/TypeScript web console, a Ray-backed agent runtime, MCP
sandbox tooling, and a Neo4j/PostgreSQL/Redis data plane.

This README is the short operational entry point. Deeper docs start at
[docs/README.md](docs/README.md).

## What Is Here

- **Agent runtime**: ReAct-style session processing, tool execution, HITL pauses,
  subagent orchestration, trace capture, and WebSocket streaming.
- **Memory and graph**: episode ingestion, memory records, entity/community graph search,
  graph schema configuration, and Neo4j-backed retrieval.
- **Workspace orchestration**: workspaces, workspace tasks, blackboard files/posts,
  topology, plan nodes, outbox workers, delivery contracts, and recovery state.
- **Sandbox and MCP**: per-project sandbox lifecycle, terminal/desktop services, MCP app
  and server management, and sandbox tool wrappers.
- **Web console**: tenant/project navigation, agent workspace, memory graph, plugin/MCP
  hub, workspace and instance management, audit/trust views, and live agent timelines.

## Stack

| Area | Current implementation |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic 2, asyncpg |
| Agent runtime | ReAct core, Ray actors, Redis streams, LiteLLM, MCP, Playwright/Tavily tools |
| Data stores | PostgreSQL 16, Redis 7, Neo4j 5.26+, MinIO |
| Frontend | React 19.2, TypeScript 5.9, Vite 7.3, Ant Design 6.1, Zustand 5, TanStack Query |
| Tooling | uv, pnpm 10, Ruff, mypy, pyright, pytest, Vitest, Playwright |

Vite 7 requires Node `^20.19.0 || >=22.12.0`; use a matching Node version for web work.

## Quick Start

```bash
make init      # copy .env if needed, install backend + web deps, start infra
make dev       # start infra, API, Ray actor worker, and web dev server
make status    # inspect local service status
make logs      # tail API and web logs
make stop      # stop background services
```

Default local URLs:

| Service | URL |
|---|---|
| API health | http://localhost:8000/health |
| Swagger UI | http://localhost:8000/docs |
| Web console | http://localhost:3000 |
| Neo4j Browser | http://localhost:7474 |
| MinIO console | http://localhost:9001 |
| Ray dashboard | http://localhost:8265 |

Default development users are created on first startup:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@memstack.ai` | `adminpassword` |
| User | `user@memstack.ai` | `userpassword` |

## Development Commands

| Task | Command |
|---|---|
| Install all deps | `make install` |
| Backend deps only | `make install-backend` |
| Web deps only | `make install-web` |
| Full dev stack | `make dev` |
| API only, foreground | `make dev-backend` |
| Web only, foreground | `make dev-web` |
| Infra only | `make infra` |
| Stop services | `make stop` |
| Unit tests | `make test-unit` |
| Integration tests | `make test-integration` |
| All tests | `make test` |
| Coverage | `make test-coverage` |
| Lint | `make lint` |
| Type check | `make type-check` |
| Full local check | `make check` |
| CI-shaped check | `make ci` |
| Alembic upgrade | `make db-migrate` |
| Alembic status | `make db-status` |

Useful focused commands:

```bash
uv run pytest src/tests/unit/test_memory_service.py -v
uv run pytest src/tests/unit/test_memory_service.py::TestMemoryService::test_create -v
cd web && pnpm run type-check
cd web && pnpm run test
```

## Repository Layout

```text
src/
  domain/                  Pure domain model, events, ports, exceptions
  application/             Services, use cases, schemas, orchestration
  infrastructure/          Web adapters, persistence, agent runtime, graph, MCP, LLM
  configuration/           Settings and DI container
  tests/                   Backend unit/integration/e2e/performance tests

web/
  src/components/          Product UI and agent/workspace components
  src/pages/               Route-level views
  src/services/            API, WebSocket, event, sandbox, MCP clients
  src/stores/              Zustand stores
  src/utils/               Event adapters, projections, helpers

sandbox-mcp-server/        MCP sandbox server and remote desktop/terminal support
sdk/python/                Python SDK package
sdk/memstack_cli/          CLI package
examples/plugins/          Plugin package templates and examples
docs/                      Current docs plus historical design/planning material
```

## Backend Architecture

The backend follows DDD and hexagonal boundaries:

- `src/domain` contains domain entities such as agents, memory, tenant/project, sandbox,
  workspace, workspace plan, MCP, audit, trust, and delivery models.
- `src/application` coordinates business workflows and use cases.
- `src/infrastructure/adapters/primary/web` exposes FastAPI routers and WebSocket handlers.
- `src/infrastructure/adapters/secondary` contains persistence, sandbox, queue, and channel
  adapters.
- `src/infrastructure/agent` contains the ReAct runtime, tool system, HITL, subagents,
  events, planning, workspace orchestration, and pool/recovery support.

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) for the current
architecture map.

## API Surface

The API is mounted primarily under `/api/v1`. Swagger and OpenAPI are generated by FastAPI
at runtime:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

Important current entry points:

| Area | Endpoints |
|---|---|
| Health | `GET /health` |
| Auth | `/api/v1/auth/*`, `/api/v1/users/me` |
| Projects and tenants | `/api/v1/projects/*`, `/api/v1/tenants/*` |
| Agent REST metadata | `/api/v1/agent/conversations`, `/api/v1/agent/tools`, `/api/v1/agent/hitl/*`, `/api/v1/agent/trace/*` |
| Agent live transport | `WS /api/v1/agent/ws` |
| Memories and episodes | `/api/v1/memories/*`, `/api/v1/episodes/*`, `/api/v1/memory/search` |
| Graph and schema | `/api/v1/graph/*`, `/api/v1/projects/{project_id}/schema/*` |
| Sandbox and terminal | `/api/v1/sandbox/*`, `/api/v1/projects/sandboxes/*`, `/api/v1/terminal/*` |
| MCP | `/api/v1/mcp/*` |
| Workspace orchestration | `/api/v1/workspaces/*`, `/api/v1/workspaces/{workspace_id}/plan`, `/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/*` |

See [docs/api-reference.md](docs/api-reference.md) for a maintained route overview.

## Agent Transport

Current live chat uses the WebSocket router:

```text
WS /api/v1/agent/ws?token=<api_key>&session_id=<client_session_id>
```

Common client messages include `send_message`, `stop_session`, `subscribe`, `unsubscribe`,
`subscribe_status`, `subscribe_lifecycle_state`, `subscribe_sandbox`, `subscribe_workspace`,
and HITL response messages. Server messages include `connected`, `ack`, `message`,
`thought`, `act`, `observe`, `text_delta`, `complete`, `error`, sandbox events, lifecycle
events, and HITL requests.

Older references to `POST /api/v1/agent/chat` are historical unless a compatibility route is
restored.

## SDKs And CLI

- Python SDK: [sdk/python/README.md](sdk/python/README.md)
- CLI: [docs/CLI.md](docs/CLI.md)

The CLI implementation still contains a legacy `chat` command targeting the old REST/SSE
chat route. Use the web console or WebSocket API for current live agent chat until the CLI
chat command is migrated.

## Environment

Start from `.env.example`:

```bash
cp .env.example .env
```

Core groups:

- API and security: `API_*`, `SECRET_KEY`, `LLM_ENCRYPTION_KEY`
- Data stores: `POSTGRES_*`, `REDIS_*`, `NEO4J_*`, `MINIO_*`
- LLM providers: `LLM_PROVIDER`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
  `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`, `ZHIPUAI_API_KEY`
- Runtime: `SANDBOX_*`, `MCP_*`, `RAY_*`, agent pool and workspace settings

Never commit real secrets. `.env.example` is the only committed environment template.

## Database And Migrations

Use Alembic for schema changes:

```bash
PYTHONPATH=. uv run alembic revision --autogenerate -m "describe change"
PYTHONPATH=. uv run alembic upgrade head
PYTHONPATH=. uv run alembic current
```

Do not edit the database directly. Current ORM models live in
`src/infrastructure/adapters/secondary/persistence/models.py` and include tenant/project,
workspace, memory, agent execution, skills, MCP, sandbox, graph, trust/audit, instance,
gene, and workspace plan tables.

## Documentation Map

Use [docs/README.md](docs/README.md) as the maintained documentation index. Many files under
`docs/` are historical plans, migration notes, or implementation summaries; keep them for
context, but treat current code and the maintained docs as source of truth.

## Contributing

Before sending changes:

```bash
make format
make lint
make test
```

For backend changes, prefer targeted pytest runs first, then broader checks. For frontend
changes, run `cd web && pnpm run type-check` plus targeted Vitest/Playwright checks.

Commit subjects must follow Conventional Commit syntax. When a body is present, follow the
Lore trailer protocol documented in [AGENTS.md](AGENTS.md).

## License

The Python package metadata declares MIT licensing in [pyproject.toml](pyproject.toml).
