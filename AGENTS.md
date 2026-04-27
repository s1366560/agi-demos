# AGENTS.md

Guidance for AI coding assistants (Copilot, Claude, Cursor, Gemini, ...) working in this repo.

**MemStack** — Enterprise AI Memory Cloud Platform. Python/FastAPI backend + React/TS frontend, DDD + Hexagonal Architecture.

> `CLAUDE.md` and `GEMINI.md` are symlinks to this file — edit here only.

## Working Principles

- **Plan before execute** for non-trivial changes; delegate to specialized agents when useful.
- **TDD**: write/adjust tests alongside code; maintain 80%+ coverage.
- **Security first**: never paste secrets (API keys, tokens, JWTs, passwords). Redact logs.
- **Code style**: no emojis in code/docs. Prefer immutability. Small files (200–400 lines typical, 800 max). Commit subjects MUST use Conventional Commit syntax with an optional scope, for example `feat(agent): add supervisor verdict tool`, `fix(sandbox): clarify read offset semantics`, `refactor(skills): lift curated lineage into domain`. Keep the first line in that format, then use the Lore protocol trailers below in the body when a body is present.
- Before editing a symbol: run `gitnexus_impact` (see GitNexus section) and report blast radius.
- Before committing: run `gitnexus_detect_changes` to verify scope.
- **Agent First (top-level architectural rule)**: every **subjective** decision point — anything that requires semantic understanding, intent inference, quality assessment, appropriateness judgment, categorization by meaning, or resolution of ambiguity — **MUST be made by an agent via a structured tool-call**. Hardcoded heuristics for subjective calls are prohibited: no regex-on-text for routing or classification, no keyword matching for intent, no `dict` lookup tables masquerading as policy engines, no hand-tuned thresholds that produce semantic verdicts on their own. The following stay deterministic because they are **structural / arithmetic / protocol** facts, not judgments:
  - set-membership checks (roster, sender-in-participants, permission allow-lists)
  - pure arithmetic (budget counters: turns, USD, wall-seconds)
  - FIFO queues, mutexes, persistence, schema enforcement
  - reading fields from a structured tool-call payload
  - static metadata declared at tool/plugin definition time (e.g. `tool.side_effects = ["payment"]`)
  - structured UI affordances (e.g. mention chips emitting `mentions: [agent_id]` on the wire) — NOT text parsing of "@xxx"
  - timers and tick triggers (the tick is objective; the verdict it triggers must be agent-judged)
  When a deterministic threshold is useful as a **cheap circuit-breaker** (e.g. doom-loop repeat count, stale-time window), it may fire the **trigger**, but the **verdict** (`healthy | stalled | looping | goal_drift`) and the **next action** (`continue | reassign | escalate`) must come from an agent tool-call. Log every judgment tool-call (agent_id, tool_name, input, output, rationale, latency) for audit. When in doubt: if the rule requires a human to write a natural-language rationale to defend it, it is subjective — delegate to an agent.

## Quick Start

```bash
make init          # First run: deps + infra + DB
make dev           # Start backend stack (API + workers + infra)
make dev-web       # Start frontend on :3000 (new terminal)
make status        # Check services
make stop          # Stop all           (alias: dev-stop)
make restart       # Stop + start
make reset         # Full wipe (docker + cache)
make fresh         # reset + init + dev
```

**Default credentials** (auto-created):

| User | Email | Password |
|------|-------|----------|
| Admin | `admin@memstack.ai` | `adminpassword` |
| User  | `user@memstack.ai`  | `userpassword` |

**Service URLs**: API `http://localhost:8000` · Swagger `/docs` · Web `http://localhost:3000`

## Common Commands

| Category | Command | Description |
|---|---|---|
| Dev | `make dev` / `stop` / `logs` / `infra` / `status` | Lifecycle + logs |
| Dev (focused) | `dev-backend`, `dev-worker`, `dev-agent-worker`, `dev-mcp-worker`, `dev-web` | Start one component |
| Test | `make test` / `test-unit` / `test-integration` / `test-coverage` / `test-watch` | Pytest + Vitest |
| Quality | `make format` / `lint` / `check` / `ci` / `type-check` / `type-check-{mypy,pyright}` | Ruff/ESLint/Mypy/Pyright |
| Hooks | `make hooks-install` | Pre-commit checks staged code + commit subject format guard |
| DB | `make db-init` / `db-reset` / `db-migrate` / `db-migrate-new` / `db-status` | Alembic |
| Docker/Sandbox | `make docker-{up,down,clean}` / `sandbox-{build,run,stop,status,shell,test}` | |
| Ray | `make ray-up-dev` / `ray-reload` | Dev mode = live code reload |
| Observability | `make obs-{start,stop,ui}` | Jaeger + OTel + Prom + Grafana |

**Run a single test**
```bash
uv run pytest src/tests/unit/test_memory_service.py -v
uv run pytest src/tests/unit/test_memory_service.py::TestMemoryService::test_create -v
uv run pytest src/tests/ -m "unit" -v
```

**Alembic**
```bash
PYTHONPATH=. uv run alembic current | history | upgrade head | downgrade -1
PYTHONPATH=. uv run alembic revision --autogenerate -m "description"   # always autogenerate, then review
```

## Architecture

```
src/
├── domain/              # Pure business logic (no external deps)
│   ├── model/           # agent/ memory/ project/ sandbox/ artifact/ mcp/ auth/ tenant/
│   ├── ports/           # Repository & service interfaces
│   └── exceptions/
├── application/         # Orchestration: services/ use_cases/ schemas/ tasks/
├── infrastructure/      # Adapters
│   ├── adapters/primary/    # FastAPI routers (driving)
│   ├── adapters/secondary/  # Persistence, external APIs (driven)
│   ├── agent/           # 4-layer ReAct Agent system
│   ├── llm/             # LiteLLM unified client
│   ├── graph/           # Neo4j knowledge graph
│   ├── mcp/             # Model Context Protocol
│   └── security/
└── configuration/       # config.py + di_container.py

web/src/                 # components/ pages/ stores/ services/ hooks/ types/
```

### Agent 4-Layer Architecture

```
L4 Agent      ReAct loop: SessionProcessor (Think→Act→Observe), DoomLoopDetector, CostTracker
L3 SubAgent   Specialized agents: Orchestrator → Router (semantic) → Executor
L2 Skill      Declarative tool compositions: Orchestrator + Executor; triggers keyword/semantic/hybrid
L1 Tool       Atomic capabilities: Terminal, Desktop, WebSearch/Scrape, Plan{Enter,Update,Exit},
              Clarification/Decision, GetEnvVar/RequestEnvVar, SandboxMCPToolWrapper
```

Execution routing (confidence-scored): `DIRECT_SKILL → SUBAGENT → PLAN_MODE → REACT_LOOP`.

### Tool → Event Pipeline

Tools are **wrapped** as `ToolDefinition` by `tool_converter.py`; the processor never sees the raw tool instance directly. To access tool methods (e.g. `consume_pending_events()`), use `getattr(tool_def, "_tool_instance", None)`.

**Emission flow** (for side-effect events like task updates):
```
Tool.execute() → self._pending_events
  → Processor consumes → yields AgentDomainEvent
  → EventConverter → event dict
  → Redis Stream (agent:events:{conversation_id})
  → agent_service.connect_chat_stream → WS bridge → frontend routeToHandler
```

**Adding a new tool event**: add `_pending_events` + `consume_pending_events()` on the tool; consume + yield in `processor.py`; add subclass in `domain/events/agent_events.py` + enum in `types.py`; add transformation in `events/converter.py` if needed; add case in frontend `agentService.routeToHandler` + handler in `streamEventHandlers.ts` + types.

**Event types**: `task_list_updated`, `task_updated`, `task_start`, `task_complete`, `artifact_created`, `artifact_ready`.

### MCP & Sandbox

| Adapter | Use | Comms |
|---|---|---|
| `MCPSandboxAdapter` | Cloud Docker containers | WebSocket |
| `LocalSandboxAdapter` | User's local machine | WebSocket + ngrok/Cloudflare tunnel |

**Tool categories (30+)**: file ops (read/write/edit/glob/grep/list/patch); code intel (ast_parse/find_symbols/find_definition/find_references/call_graph); editing (edit_by_ast/batch_edit/preview_edit); testing (generate_tests/run_tests/analyze_coverage); git (diff/log/generate_commit); terminal/desktop (ttyd + noVNC).

### HITL (Human-in-the-Loop) Types

`clarification` · `decision` · `env_var` · `permission`. Run as asyncio tasks with retry and TaskLog status.

## ⚠️ Critical Gotchas

### DB Session & DI Container

The global `request.app.state.container` has `db=None` — it is **only** for singletons (neo4j_client, redis, graph_service). Using it for DB-dependent services → `AttributeError: 'NoneType' has no attribute 'execute'`.

**Correct patterns:**
```python
# Pattern A — scoped container (when you need the full DI tree)
from .utils import get_container_with_db
async def list_items(request: Request, db: AsyncSession = Depends(get_db)):
    container = get_container_with_db(request, db)
    return await container.some_service().list()

# Pattern B — direct construction (focused services)
async def get_plan_coordinator(db: AsyncSession = Depends(get_db)):
    return PlanCoordinator(plan_repo=SqlPlanRepository(db), ...)
```

**Rules**:
- Repositories take `AsyncSession` as first arg: `SqlXxxRepository(db)`.
- `Depends(get_db)` sessions auto-close but do **not** auto-commit — the endpoint must `await db.commit()`.
- `DIContainer.with_db(db)` clones the global container with a real session if needed.

### Frontend: Zustand `useShallow`

Object selectors **must** use `useShallow` or you get an infinite re-render:
```tsx
import { useShallow } from 'zustand/react/shallow';
const { a, b } = useStore(useShallow((s) => ({ a: s.a, b: s.b })));  // ✅
const { a, b } = useStore((s) => ({ a: s.a, b: s.b }));              // ❌ infinite loop
const a = useStore((s) => s.a);                                       // ✅ single value, no shallow needed
```

### Frontend: API paths

`httpClient` already sets `baseURL: '/api/v1'`. Service paths must be relative:
```ts
const BASE_URL = '/mcp/apps';         // ✅
const BASE_URL = '/api/v1/mcp/apps';  // ❌ doubles the prefix
```

### Frontend: Trailing slashes on collection endpoints

FastAPI's `redirect_slashes` returns 307 with a cross-origin `Location` (Vite 3000 → backend 8000). Browsers strip the `Authorization` header on cross-origin redirects → silent 401 → redirect to `/login`.

```ts
list:   (p) => httpClient.get(`${BASE_URL}/`, { params: p });   // ✅
create: (d) => httpClient.post(`${BASE_URL}/`, d);              // ✅
getById:(id) => httpClient.get(`${BASE_URL}/${id}`);            // ✅ (sub-resource, no redirect)
```

### Agent: Runtime guidance & sessions

- `SessionProcessor` injects `_session_instructions` / `_response_instructions` as a `[Runtime Guidance]` system message on every LLM call.
- Selected agent prompts are appended as `agent_definition_prompt`, not used as base system identity.
- `sessions_history` reads from DB repositories, not the Redis agent stream.
- Conversations are stateful — always pass `conversation_id`.

### Ray Actor code changes

Ray actors run from baked Docker images — local edits do **not** take effect until rebuild. Use `make ray-up-dev` for volume-mounted live reload, or `make ray-reload` to restart actors after a code change.

### Logging

`main.py` calls `logging.basicConfig()` at import; without this all `src.*` loggers silently discard output. `LOG_LEVEL` env controls level (default `INFO`). Ray actor-side logs: `docker logs memstack-ray-worker` or the Ray worker log files.

### A2UI / HITL specifics

- HITL allowed actions are derived from persisted block content; responses validate `source_component_id` + `action_name` membership.
- A2UI incremental updates merge JSONL deltas with prior surface state before validate + persist.
- `env_var` HITL stream payloads must use `response_data_encrypted` (plaintext is rejected); recovery replays sealed `response_metadata`.
- Feishu adapter: card-action HITL responses must be marshaled onto the captured app loop, not the websocket callback loop.

### Never

- Modify the DB directly — always Alembic migrations.
- Use find-and-replace for renames — use `gitnexus_rename` (understands call graph).

## Coding Standards

### Python

- Line length **100**. Formatter `ruff format`. Linter `ruff check` (E, F, I, N, UP, B, C4, SIM, RUF, ANN, C901, PLR091).
- Type check: `mypy` + `pyright` (both strict; excludes tests/alembic/legacy).
- **Async everywhere** for DB/HTTP.
- Domain entities: `@dataclass(kw_only=True)`; value objects: `@dataclass(frozen=True)`.
- Naming: `PascalCase` classes, `snake_case` funcs/vars, `UPPER_SNAKE_CASE` constants, `_leading_underscore` private.
- Import order (auto): future → stdlib → third-party → `src.*` → relative.
- **Multi-tenancy**: always scope queries by `project_id` / `tenant_id`.
- Git hooks (after `hooks-install`) run pre-commit checks on staged code and validate commit subjects against the repo's Conventional Commit format. See `docs/TYPE_SAFETY.md`.

Patterns for new domain/application/infrastructure layers follow standard DDD; examples: `src/domain/model/memory/`, `src/infrastructure/adapters/secondary/persistence/sql_*.py`, `src/application/services/*`.

### TypeScript / React

- Prettier (100 width, single quotes, semicolons). ESLint with TS + React + import plugins.
- Naming: components `PascalCase.tsx`, hooks `use*`, services `camelCase.ts`, stores `*Store.ts`, props `ComponentNameProps`.
- Import order (auto): React/RR → external libs → `@/stores` → `@/services` → `@/hooks` → `@/components` → `type` imports → styles.
- **Anti-barrel**: prefer direct imports (`@/components/ui/Button`) over `@/components`.
- Type-only imports: `import type { ... }`.

### Testing

- Python: `test_{module}.py` / `Test{Component}` / `test_{scenario}_{expected}`. Markers `@pytest.mark.unit` / `@pytest.mark.integration`. `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed. Key fixtures: `db_session`, `test_user`, `test_project_db`, `authenticated_client`.
- TS: unit `{Component}.test.tsx`, E2E `{feature}.spec.ts` (Playwright).

## Core Domain Concepts

| Concept | Description |
|---|---|
| Episode | A discrete interaction (content + metadata) |
| Memory | Semantic memory extracted from episodes, stored in Neo4j |
| Entity | Real-world object with attributes and relationships |
| Project | Multi-tenant isolation unit with its own knowledge graph |
| Skill | Declarative tool composition with trigger patterns |
| SubAgent | Specialized autonomous agent for a task type |
| API Key | `ms_sk_` + 64 hex chars, stored as SHA256 hash |

## Key Files

| Area | Path |
|---|---|
| API entry | `src/infrastructure/adapters/primary/web/main.py` |
| Config | `src/configuration/config.py`, `di_container.py` |
| ReAct agent | `src/infrastructure/agent/core/react_agent.py` |
| Session processor | `src/infrastructure/agent/processor/processor.py` |
| Tool wrapping | `src/infrastructure/agent/core/tool_converter.py` |
| Tools | `src/infrastructure/agent/tools/` (see `todo_tools.py` for pending-events pattern) |
| Skill orchestration | `src/infrastructure/agent/skill/orchestrator.py` |
| Routing | `src/infrastructure/agent/routing/{execution,binding,default_message}_router.py`, `intent_gate.py` |
| Events | `src/domain/events/{agent_events,types}.py`, `src/infrastructure/agent/events/converter.py` |
| Actor exec | `src/infrastructure/agent/actor/execution.py` |
| Graph | `src/infrastructure/graph/native_graph_adapter.py`, `extraction/entity_extractor.py`, `search/hybrid_search.py` |
| Frontend | `web/src/App.tsx`, `pages/tenant/AgentWorkspace.tsx`, `stores/agentV3.ts`, `services/agentService.ts` |

## API Testing

```bash
# Login → temp ms_sk key
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@memstack.ai&password=adminpassword"

export API_KEY="ms_sk_..."
curl -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/v1/projects

# Agent chat (SSE)
curl -N http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"conversation_id":"...","message":"Hello","project_id":"1"}'
```

The WS endpoint `/api/v1/agent/ws` authenticates via `?token=<api_key>` query param.

## Tech Stack

- **Backend** Python 3.12+ · FastAPI 0.104+ · SQLAlchemy 2.0+ · PostgreSQL 16+ · Redis 7+ · Neo4j 5.26+
- **Workflow** asyncio + Ray Actors
- **LLM** LiteLLM (Gemini, Dashscope, Deepseek, OpenAI, Anthropic)
- **Frontend** React 19.2+ · TypeScript 5.9+ · Vite 7.3+ · Ant Design 6.1+ · Zustand 5.0+
- **Testing** pytest 7.4+ · Vitest · Playwright · 80%+ coverage target

## Environment Variables

Core groups (see `.env.example` for full list): `API_*` · `SECRET_KEY`, `LLM_ENCRYPTION_KEY` · `NEO4J_*` · `POSTGRES_*` · `REDIS_*` · `LLM_PROVIDER` + provider keys (`GEMINI_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`, ...) · `SANDBOX_*` · `MCP_*`.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **agi-demos** (59028 symbols, 160638 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/agi-demos/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/agi-demos/context` | Codebase overview, check index freshness |
| `gitnexus://repo/agi-demos/clusters` | All functional areas |
| `gitnexus://repo/agi-demos/processes` | All execution flows |
| `gitnexus://repo/agi-demos/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:
1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## Keeping the Index Fresh

After committing code changes, the GitNexus index becomes stale. Re-run analyze to update it:

```bash
npx gitnexus analyze
```

If the index previously included embeddings, preserve them by adding `--embeddings`:

```bash
npx gitnexus analyze --embeddings
```

To check whether embeddings exist, inspect `.gitnexus/meta.json` — the `stats.embeddings` field shows the count (0 means no embeddings). **Running analyze without `--embeddings` will delete any previously generated embeddings.**

> Claude Code users: A PostToolUse hook handles this automatically after `git commit` and `git merge`.

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Browser Automation

`agent-browser` for web automation (`agent-browser --help`). Core flow:
1. `agent-browser open <url>`
2. `agent-browser snapshot -i` → interactive elements with refs (`@e1`, ...)
3. `agent-browser click @e1` / `fill @e2 "text"`
4. Re-snapshot after page changes.
