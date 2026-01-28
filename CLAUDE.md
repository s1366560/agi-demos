# CLAUDE.md

## Quick Start (Environment Setup & Reset)

**First time setup:**

```bash
make init                 # Install deps + start infra + init database (one command!)
make dev                  # Start backend services
make dev-web              # Start frontend (in another terminal)
```

**Daily development:**

```bash
make dev                  # Start backend
make status               # Check service status
```

**Environment reset (when things break):**

```bash
make restart              # Quick restart services
make clean                # Complete reset (stop + clean Docker + clean cache)
```

**Default credentials after init:**

- Admin: `admin@memstack.ai` / `adminpassword`
- User: `user@memstack.ai` / `userpassword`

## Common Development Commands

### Setup & Installation

```bash
make install              # Install all dependencies (backend + web)
make install-backend      # Install Python dependencies with uv
make install-web          # Install frontend dependencies with pnpm
```

### Running Services

```bash
make dev                  # Start all backend services (API + worker + infra)
make dev-backend          # Start API server only (foreground, port 8000)
make dev-worker           # Start worker service only (foreground)
make dev-web              # Start web dev server (port 3000)
make dev-infra            # Start Neo4j, PostgreSQL, Redis, MinIO via Docker
make dev-stop             # Stop all background services
make dev-logs             # Tail all service logs
make status               # Show status of all services
```

### Testing

```bash
# Backend tests
make test                 # Run all tests (backend + web)
make test-backend         # Backend tests only
make test-unit            # Unit tests only (fast)
make test-integration     # Integration tests only
make test-performance     # Performance tests only
make test-coverage        # Run with coverage report (80%+ target)
make test-watch           # Run tests in watch mode

# Frontend tests
make test-web             # Run frontend tests (Vitest)
make test-e2e             # E2E tests (Playwright, requires services running)

# Run single test file or function
uv run pytest src/tests/unit/test_specific.py -v
uv run pytest src/tests/unit/test_specific.py::test_function -v

# Run tests by marker
uv run pytest src/tests/ -m "unit" -v
uv run pytest src/tests/ -m "integration" -v
uv run pytest src/tests/ -m "performance" -v
```

### Code Quality

```bash
make format               # Format all code (ruff format + lint fix)
make format-backend       # Format Python code only
make lint                 # Lint all code
make lint-backend         # Lint Python (ruff + mypy)
make check                # Run format + lint + test
```

### Database Operations

```bash
make db-init              # Initialize PostgreSQL database
make db-migrate           # Run Alembic migrations (upgrade to latest)
make db-reset             # WARNING: Drops and recreates database
make db-shell             # Open PostgreSQL shell
make db-status            # Show Alembic migration status

# Alembic commands (advanced)
PYTHONPATH=. uv run alembic current                    # Show current revision
PYTHONPATH=. uv run alembic history                    # Show migration history
PYTHONPATH=. uv run alembic heads                      # Show head revisions
PYTHONPATH=. uv run alembic revision --autogenerate -m "description"  # Generate migration
PYTHONPATH=. uv run alembic upgrade head               # Apply all migrations
PYTHONPATH=. uv run alembic downgrade -1               # Rollback one migration
PYTHONPATH=. uv run alembic stamp head                 # Mark DB as current (use carefully)
```

### Docker Operations

```bash
make docker-up            # Start all Docker services
make docker-down          # Stop Docker services
make docker-logs          # Show Docker logs (follow mode)
```

### Test Data & SDK

```bash
make test-data            # Generate test data (default: 50 random episodes)
make sdk-install          # Install SDK in development mode
make sdk-test             # Run SDK tests
```

### API Testing

**Getting API Key:**

After `make init`, check logs for auto-generated API keys:

```bash
tail -50 logs/api.log | grep "API Key"
# Output: 🔑 Default Admin API Key created: ms_sk_xxx...
```

Or login to get a token:

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@memstack.ai&password=adminpassword"
```

**API Key Format:** `ms_sk_` + 64 hex characters (stored as SHA256 hash)

**Testing APIs with curl:**

```bash
# Set API key
export API_KEY="ms_sk_your_key_here"

# List projects
curl -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/v1/projects

# Create episode
curl -X POST http://localhost:8000/api/v1/episodes \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "1", "content": "Test content"}'

# Search memories
curl -X POST http://localhost:8000/api/v1/search \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "1", "query": "search term"}'

# Agent chat (SSE streaming)
curl -N http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "conv-id", "message": "Hello", "project_id": "1"}'
```

**Default Credentials:**
| User | Email | Password | Role |
|------|-------|----------|------|
| Admin | `admin@memstack.ai` | `adminpassword` | admin |
| User | `user@memstack.ai` | `userpassword` | user |

**API Documentation:**

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

**Temporal UI (Workflow Monitoring):**

- Temporal UI: http://localhost:8080/namespaces/default
- Default namespace: `default`

**Key Authentication Files:**

- Auth dependencies: `src/infrastructure/adapters/primary/web/dependencies/auth_dependencies.py`
- Auth service: `src/application/services/auth_service_v2.py`
- API key model: `src/domain/model/auth/api_key.py`
- Auth routes: `src/infrastructure/adapters/primary/web/routers/auth.py`

## Architecture Overview

MemStack follows **Domain Driven Design (DDD) + Hexagonal Architecture** with strict layer separation:

```
src/
├── domain/                    # Core business logic (no external dependencies)
│   ├── model/                # Domain entities organized by bounded context
│   │   ├── agent/           # React Agent entities (Conversation, Message, WorkPlan, etc.)
│   │   ├── auth/            # Authentication entities (User, APIKey, Roles, Permissions)
│   │   ├── memory/          # Memory entities (Episode, Memory, Entity, Community)
│   │   ├── project/         # Project entities
│   │   ├── tenant/          # Tenant entities
│   │   └── task/            # Task entities
│   ├── ports/               # Repository and service interfaces (dependency inversion)
│   │   ├── repositories/    # Repository interfaces
│   │   └── services/        # Service ports (graph_service, queue, agent_service)
│   └── llm_providers/       # LLM provider abstractions
│
├── application/              # Application orchestration layer
│   ├── services/            # Application services
│   │   ├── agent_service.py        # Agent orchestration
│   │   ├── memory_service.py       # Memory management
│   │   ├── workflow_learner.py     # Pattern learning from executions
│   │   └── ...
│   ├── use_cases/           # Business use cases organized by domain
│   │   ├── agent/          # Agent use cases (Chat, PlanWork, ExecuteStep, etc.)
│   │   ├── memory/         # Memory CRUD use cases
│   │   └── auth/           # Authentication use cases
│   ├── schemas/             # DTOs for API requests/responses
│   └── tasks/               # Background task handlers
│
├── infrastructure/           # External implementations (adapters)
│   ├── adapters/
│   │   ├── primary/         # Driving adapters (web API, CLI)
│   │   │   └── web/
│   │   │       ├── main.py              # FastAPI app entry point
│   │   │       ├── routers/             # API endpoint modules (20+)
│   │   │       └── dependencies.py      # Dependency injection
│   │   │
│   │   └── secondary/       # Driven adapters (databases, external APIs)
│   │       ├── persistence/  # SQLAlchemy repository implementations
│   │       ├── queue/        # Redis queue adapter
│   │       └── cache/        # Cached repository decorators
│   │
│   ├── agent/               # Agent infrastructure (React Agent System)
│   │   ├── core/                   # Self-developed ReAct Core
│   │   │   ├── react_agent.py      # ReAct agent engine
│   │   │   ├── processor.py        # SessionProcessor - core reasoning loop
│   │   │   ├── llm_stream.py       # Streaming LLM interface
│   │   │   ├── events.py           # SSE event definitions
│   │   │   ├── skill_executor.py   # L2 Skill system
│   │   │   └── subagent_router.py  # L3 SubAgent routing
│   │   ├── permission/             # Permission management
│   │   ├── doom_loop/              # Doom loop detection
│   │   ├── cost/                   # Cost tracking
│   │   ├── retry/                  # Intelligent retry strategy
│   │   ├── tools/                 # Agent tools (10+ tools)
│   │   └── output/                # Structured output formatters
│   ├── llm/                 # LLM provider clients
│   │   ├── litellm/        # LiteLLM multi-provider client
│   │   └── qwen/           # Alibaba Qwen client
│   ├── security/            # Authentication, authorization, audit logging
│   └── audit/               # Audit log service
│
└── configuration/            # Settings and DI container
    ├── config.py            # Pydantic Settings (environment variables)
    ├── di_container.py      # Dependency injection setup (20+ factories)
    └── factories.py         # Client factory functions
```

### Key Architectural Principles

1. **Dependency Inversion**: Domain defines repository interfaces, infrastructure implements them
2. **Port & Adapter**: Application logic independent of frameworks/databases
3. **Repository Pattern**: All data access abstracted behind interfaces
4. **Service Separation**:
   - **Domain Services**: Business logic (stateless, operates on entities)
   - **Application Services**: Orchestration (coordinates repositories, domain services)
5. **Aggregate Boundaries**: Entities grouped with clear aggregate roots

### Technology Stack

**Backend**:

- Python 3.12+, FastAPI 0.110+, Pydantic 2.5+
- Neo4j 5.26+ (knowledge graph), PostgreSQL 16+ (metadata), Redis 7+ (cache)
- SQLAlchemy 2.0+ (ORM), Alembic (migrations)
- Temporal.io (enterprise workflow orchestration)
- Native Graph Adapter (自研知识图谱引擎)
- Self-developed ReAct Core (replaces LangGraph)
- LangChain (LLM utilities, not for agent framework)
- LiteLLM (multiple LLM provider support: Gemini, Qwen, Deepseek, ZhipuAI, OpenAI)

**Frontend** (web/):

- React 19.2+, TypeScript 5.9+, Vite 7.3+
- Ant Design 6.1+ (UI), Zustand 5.0+ (state)
- Vitest 4.0+ (unit tests), Playwright 1.57+ (E2E)

**Testing**:

- **Backend**: pytest 9.0+, pytest-asyncio (async tests)
- **Frontend**: Vitest 4.0+ (unit tests), Playwright 1.57+ (E2E)
- 80%+ coverage target with `make test-coverage`
- Test markers: `unit`, `integration`, `performance`

## Understanding the Codebase

### Core Domain Concepts

**Episodes**: Discrete interactions/events containing content, metadata, and extracted entities. Processed asynchronously to extract knowledge.

**Memories**: Semantic memory derived from episodes - facts, relationships, and temporal context stored in Neo4j knowledge graph.

**Entities**: Real-world objects (people, organizations, concepts) with attributes and relationships.

**Projects**: Multi-tenant isolation units. Each project has its own knowledge graph and memories.

**API Keys**: Authentication mechanism using SHA256-hashed keys (format: `ms_sk_` + 64 hex chars).

### React Agent System

The **React Agent** is a multi-level thinking AI agent built with **self-developed ReAct Core** (replaces LangGraph):

**Architecture Layers**:

- **L1: Tool Layer** - Atomic capability units (10+ built-in tools)
- **L2: Skill Layer** - Declarative tool compositions with triggers
- **L3: SubAgent Layer** - Specialized agents with domain expertise
- **L4: Agent Layer** - Complete ReAct agent with multi-level thinking

**Key Components**:

- **ReActAgent** (`core/react_agent.py`) - Main agent class
- **SessionProcessor** (`core/processor.py`) - Core ReAct reasoning loop
- **LLMStream** (`core/llm_stream.py`) - Streaming LLM interface via LiteLLM
- **PermissionManager** (`permission/manager.py`) - Allow/Deny/Ask permission control
- **DoomLoopDetector** (`doom_loop/detector.py`) - Detects stuck agent loops
- **CostTracker** (`cost/tracker.py`) - Real-time token and cost calculation

**Agent Tools** (located in `src/infrastructure/agent/tools/`):

- `MemorySearch` - Semantic memory search
- `EntityLookup` - Find entities in knowledge graph
- `GraphQuery` - Execute Cypher graph queries
- `MemoryCreate` - Create new memories
- `EpisodeRetrieval` - Retrieve past episodes
- `Summary` - Generate summaries
- `WebSearch` - Web search
- `WebScrape` - Web page scraping
- `Clarification` - Ask clarifying questions
- `Decision` - Request user decisions

**Agent Flow**:

```
User Query → POST /api/v1/agent/chat (SSE streaming)
  → ChatUseCase
    → AgentService.stream_chat_v2()
      → ReActAgent.stream()
        → SubAgentRouter.match() (L3)
        → SkillExecutor.match() (L2)
        → SessionProcessor.process()
          → LLMStream.generate() (LiteLLM)
          → Tool Execution with Permission Check
          → Doom Loop Detection
          → Cost Tracking
        → SSE Events → Frontend (real-time)
```

### Request Flow

```
HTTP Request
  → FastAPI Router (infrastructure/adapters/primary/web/routers/)
    → Application Service (application/services/)
      → Repository Interface (domain/repositories/)
        → Repository Implementation (infrastructure/adapters/secondary/persistence/)
          → Database (PostgreSQL/Neo4j)
      → Domain Service (domain/services/) [optional]
      → Domain Entity (domain/entities/)
    ← Response DTO
```

### Async Processing

**Temporal.io Workflow Orchestration** (Primary Method):

Episodes are processed asynchronously using **Temporal.io** enterprise workflow engine:

1. Episode created → returns 202 Accepted
2. Temporal Worker picks up workflow task
3. Executes Episode processing workflow:
   - **ExtractEntitiesActivity**: LLM extracts entities with structured output
   - **DeduplicateEntitiesActivity**: Vector similarity-based entity merging
   - **SaveEntitiesActivity**: Persist entities to Neo4j
   - **ExtractRelationshipsActivity**: Discover entity relationships
   - **SaveRelationshipsActivity**: Create relationship edges
   - **UpdateCommunitiesActivity**: Louvain community detection + LLM summary
4. Knowledge graph updated in Neo4j
5. Episode status updated to "Synced" in PostgreSQL

**Temporal Architecture**:

```
src/infrastructure/adapters/secondary/temporal/
├── adapter.py                     # TemporalAdapter (implements WorkflowEnginePort)
├── client.py                      # Temporal client wrapper
├── worker_state.py                # Worker lifecycle management
├── workflows/
│   ├── episode.py                 # Episode processing workflow
│   ├── entity.py                  # Entity extraction workflow
│   └── community.py               # Community update workflow
└── activities/
    ├── episode.py                 # Episode-related activities
    ├── entity.py                  # Entity extraction activities
    └── community.py               # Community detection activities
```

**Configuration**:

```yaml
# temporal-config/development.yaml
server:
  rpc: localhost:7233
  ui: localhost:8233
# docker-compose.yml includes:
# - temporal (server)
# - temporal-ui (web UI)
# - temporal-postgresql (metadata DB)
```

**Worker Entry Point**: `src/worker_temporal.py`

**Legacy Redis Queue** (Deprecated):

- Previous implementation using Redis queue (`src/worker.py`)
- Being phased out in favor of Temporal.io

### Knowledge Graph System (Native Graph Adapter)

The **Native Graph Adapter** is a self-developed knowledge graph engine:

**Architecture**:

```
src/infrastructure/graph/
├── native_graph_adapter.py        # Main adapter (implements GraphServicePort)
├── neo4j_client.py                # Neo4j driver wrapper
├── schemas.py                     # Pydantic models for nodes/edges
├── extraction/
│   ├── entity_extractor.py        # LLM-driven entity extraction
│   ├── relationship_extractor.py  # LLM-driven relationship discovery
│   ├── reflexion.py               # Reflexion iteration for completeness
│   └── prompts.py                 # Prompt templates
├── embedding/
│   └── embedding_service.py       # Vector embedding service wrapper
├── search/
│   └── hybrid_search.py           # Hybrid search (vector + keyword + RRF)
└── community/
    ├── louvain_detector.py        # Community detection algorithm
    └── community_updater.py       # Community summary generation
```

**Key Features**:

- **Entity Extraction**: LLM-driven with structured JSON output
- **Relationship Discovery**: Automatic relationship detection between entities
- **Reflexion Iteration**: Optional second-pass to catch missed entities
- **Entity Deduplication**: Vector similarity matching to merge duplicates
- **Hybrid Search**: Combined vector + keyword search with RRF fusion
- **Community Detection**: Louvain algorithm for entity clustering

**Episode Processing Flow**:

```
Episode Content
  → EntityExtractor.extract() (LLM structured output)
  → EntityExtractor.dedupe() (vector similarity)
  → Save Entity nodes + MENTIONS relationships
  → RelationshipExtractor.extract() (LLM)
  → Save RELATES_TO relationships
  → CommunityUpdater.update() (Louvain + LLM summary)
  → Update Episode status to "Synced"
```

**Neo4j Schema**:

- `(:Episodic)` - Episode nodes with content and metadata
- `(:Entity)` - Entity nodes with embeddings and attributes
- `(:Community)` - Community nodes with member summaries
- `[:MENTIONS]` - Episode → Entity relationships
- `[:RELATES_TO]` - Entity → Entity relationships with weights
- `[:BELONGS_TO]` - Entity → Community membership

**Configuration**:

```python
# Enable native adapter (config.py)
USE_NATIVE_GRAPH_ADAPTER: bool = True  # Default: True
```

### LLM Integration

Multiple LLM providers supported via LiteLLM (configured via `LLM_PROVIDER` env var):

- **Google Gemini**: Entity extraction, summarization (default)
- **Alibaba Qwen**: Chinese language optimization, embedding, reranking
- **Deepseek**: Cost-effective reasoning
- **ZhipuAI**: Chinese language model
- **OpenAI**: GPT models

LiteLLM abstraction layer allows easy provider switching and unified API.

### Frontend Testing

**Vitest** (Unit Tests):

```bash
cd web && pnpm run test           # Run all unit tests
cd web && pnpm run test:coverage  # Run with coverage
cd web && pnpm run test:watch     # Watch mode
```

**Playwright** (E2E Tests):

```bash
cd web && pnpm run test:e2e       # Run E2E tests (requires services running)
```

**Type Checking**:

```bash
cd web && pnpm run type-check     # TypeScript type checking
```

Frontend tests are located in `web/src/test/` and use Testing Library for component testing.

## Database Schema

**PostgreSQL** (metadata):

- `users`, `tenants`, `projects` - Multi-tenant structure
- `api_keys` - Authentication (SHA256 hashed)
- `episodes` - Episode metadata and content
- `llm_provider_configs` - LLM provider settings

**Neo4j** (knowledge graph):

- Nodes: Entities with attributes
- Relationships: Typed edges with weights
- Temporal: `created_at`, `valid_at` timestamps for historical queries

**Redis** (cache):

- Session data, frequently accessed queries

## Configuration

Environment variables (see `.env.example`):

- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` - Neo4j connection
- `DATABASE_URL` - PostgreSQL connection
- `REDIS_URL` - Redis connection
- `TEMPORAL_HOST` - Temporal server host (default: localhost)
- `TEMPORAL_PORT` - Temporal server port (default: 7233)
- `TEMPORAL_NAMESPACE` - Temporal namespace (default: default)
- `TEMPORAL_TASK_QUEUE` - Task queue name (default: memstack-tasks)
- `LLM_PROVIDER` - "gemini", "qwen", "deepseek", "zhipu", "openai"
- `GEMINI_API_KEY` - Google Gemini API key
- `DASHSCOPE_API_KEY` - Alibaba Qwen API key
- `DEEPSEEK_API_KEY` - Deepseek API key
- `ZHIPUAI_API_KEY` - ZhipuAI API key
- `OPENAI_API_KEY` - OpenAI API key

Configuration loaded via `src/configuration/config.py` using Pydantic Settings.

## Dependency Injection

The `DIContainer` (src/configuration/di_container.py) manages dependencies:

- Session factories for database access
- NativeGraphAdapter for Neo4j knowledge graph operations
- Repository implementations injected into application services
- Agent-related dependencies (ReActAgent, SessionProcessor, PermissionManager, CostTracker)

### Frontend Architecture

The React frontend uses **Zustand** for state management and **Ant Design** for UI components:

```
web/src/
├── pages/                  # Route-level page components
│   ├── project/           # Project-scoped pages (13 pages)
│   │   ├── AgentChat.tsx           # Multi-level thinking agent chat
│   │   ├── EnhancedSearch.tsx      # Advanced memory search
│   │   ├── MemoryList.tsx          # Memory management
│   │   ├── CommunitiesList.tsx     # Community visualization
│   │   └── EntitiesList.tsx        # Entity browser
│   └── tenant/            # Tenant management pages (13 pages)
│       ├── AgentDashboard.tsx      # Agent conversation management
│       ├── TaskDashboard.tsx       # Background task monitoring
│       └── ProviderList.tsx        # LLM provider configuration
│
├── components/            # Reusable UI components
│   ├── agent/            # Agent-specific components (15+)
│   │   ├── ChatInterface.tsx       # Main chat UI
│   │   ├── MessageBubble.tsx       # Message display
│   │   ├── WorkPlanCard.tsx        # Work plan visualization
│   │   └── TenantAgentConfigEditor.tsx  # Config UI
│   └── ...
│
├── services/             # API clients
│   ├── agentService.ts           # Agent API with SSE streaming
│   ├── agentConfigService.ts     # Configuration management
│   ├── graphService.ts           # Knowledge graph API
│   └── memoryService.ts          # Memory operations
│
├── stores/               # Zustand state management
│   ├── agent.ts         # Agent state (conversations, messages, plans)
│   ├── auth.ts          # Authentication state
│   ├── memory.ts        # Memory state
│   └── project.ts       # Project state
│
└── test/                 # Frontend tests
    └── integration/      # Integration tests (e.g., agentRouting.test.tsx)
```

**Key Frontend Features**:

- **SSE Streaming**: Real-time agent responses via `agentService.chat()`
- **Multi-level Thinking**: Visual work plans and step execution
- **Report Viewer**: Structured output (tables, markdown, code)

### SSE Streaming

The agent uses **Server-Sent Events (SSE)** for real-time communication:

**Backend** (`src/infrastructure/adapters/primary/web/routers/agent.py`):

- `POST /api/v1/agent/chat` - Returns `StreamingResponse` with SSE events
- Events: `plan`, `step`, `thought`, `observation`, `result`, `error`

**Frontend** (`web/src/services/agentService.ts`):

- `chat()` method with `EventSource` or `fetch` with `ReadableStream`
- Parses SSE events and updates Zustand store in real-time

**Event Types**:

```typescript
{ type: "plan", data: WorkPlan }
{ type: "step", data: PlanStep }
{ type: "thought", data: { content: string } }
{ type: "observation", data: { content: string } }
{ type: "result", data: { content: string, format: "markdown"|"table"|"code" } }
{ type: "error", data: { message: string } }
```

## Key File Locations

### Backend Entry Points

- API: `src/infrastructure/adapters/primary/web/main.py`
- Worker: `src/worker.py`
- Config: `src/configuration/config.py`
- DI Container: `src/configuration/di_container.py`

### Agent System (Backend)

- ReAct Agent: `src/infrastructure/agent/core/react_agent.py`
- Session Processor: `src/infrastructure/agent/core/processor.py`
- LLM Stream: `src/infrastructure/agent/core/llm_stream.py`
- Permission Manager: `src/infrastructure/agent/permission/manager.py`
- Cost Tracker: `src/infrastructure/agent/cost/tracker.py`
- Agent Tools: `src/infrastructure/agent/tools/`
- Agent Use Cases: `src/application/use_cases/agent/`
- Agent Domain Models: `src/domain/model/agent/`
- Agent Router: `src/infrastructure/adapters/primary/web/routers/agent.py`

### Frontend Entry Points

- App: `web/src/App.tsx`
- Main: `web/src/main.tsx`
- Agent Chat Page: `web/src/pages/project/AgentChat.tsx`
- Agent Store: `web/src/stores/agent.ts`
- Agent Service: `web/src/services/agentService.ts`

### Frontend Components

- Chat Interface: `web/src/components/agent/ChatInterface.tsx`
- Message Bubble: `web/src/components/agent/MessageBubble.tsx`
- Work Plan Card: `web/src/components/agent/WorkPlanCard.tsx`
- Tool Execution: `web/src/components/agent/ToolExecutionCard.tsx`

## Testing Patterns

### Backend Testing

Tests use `asyncio_mode = "auto"` - no need to mark async tests with `@pytest.mark.asyncio`.

**Unit Tests**: Mock all external dependencies (databases, LLM APIs)

```python
# Example: src/tests/unit/
async def test_episode_creation(test_db, test_user):
    # Fixtures automatically provide database and user
    pass
```

**Integration Tests**: Real databases, test configuration

```python
# Example: src/tests/integration/
@pytest.mark.integration
async def test_episode_crud(test_db, test_project_db):
    # Uses test databases (SQLite in-memory)
    pass
```

### Frontend Testing

**Unit Tests** (Vitest + Testing Library):

```typescript
// Example: web/src/components/__tests__/MessageBubble.test.tsx
import { render, screen } from "@testing-library/react";
import { MessageBubble } from "../MessageBubble";

describe("MessageBubble", () => {
  it("renders message content", () => {
    render(<MessageBubble message={{ content: "Hello", role: "user" }} />);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
});
```

**Integration Tests**:

```typescript
// Example: web/src/test/integration/agentRouting.test.tsx
// Tests full agent workflow with mocked API
```

**E2E Tests** (Playwright):

```typescript
// Example: web/e2e/agentChat.spec.ts
import { test, expect } from "@playwright/test";

test("agent chat flow", async ({ page }) => {
  await page.goto("/project/1/agent");
  await page.fill('[data-testid="chat-input"]', "Hello");
  await page.click('[data-testid="send-button"]');
  await expect(page.locator('[data-testid="message-bubble"]')).toBeVisible();
});
```

**Key Test Fixtures** (from `src/tests/conftest.py`):

- `test_db` / `db_session`: In-memory SQLite async session
- `test_user`: User record in database
- `test_tenant_db`: Tenant with owner relationship
- `test_project_db`: Project with user membership
- `test_memory_db`: Memory attached to project
- `mock_neo4j_client`: Mock Neo4j client for direct queries
- `mock_graph_service`: Mock GraphServicePort (NativeGraphAdapter)
- `client`: FastAPI TestClient
- `authenticated_client`: TestClient with auth header
- `async_client`: Async HTTPX client for async tests

## Migration Strategy

Alembic migrations auto-run on application startup via lifespan hook:

```python
# src/infrastructure/adapters/primary/web/main.py:51
await run_alembic_migrations()
```

Migration files in `alembic/versions/`. Create new migrations:

```bash
# Manual migration creation (if needed)
PYTHONPATH=. uv run alembic revision --autogenerate -m "description"
```

### Alembic Migration Guidelines

#### Critical Rules

1. **NEVER modify database directly without migrations**

   - Always use Alembic migrations for schema changes
   - Direct SQL changes bypass the version tracking system
   - This causes the `alembic_version` table to be out of sync

2. **Always use `--autogenerate` for schema changes**

   ```bash
   # 1. Modify SQLAlchemy models in src/infrastructure/adapters/secondary/persistence/models.py
   # 2. Generate migration
   PYTHONPATH=. uv run alembic revision --autogenerate -m "description"
   # 3. Review the generated migration file
   # 4. Edit if needed (see below)
   # 5. Test migration
   PYTHONPATH=. uv run alembic upgrade head
   ```

3. **Review autogenerated migrations**
   - Autogenerated migrations may include false positives or miss operations
   - Always review and edit before committing
   - Common issues:
     - Detects existing indexes as new (comment out or remove)
     - Misses `ALTER TABLE` for column renames (must add manually)
     - Doesn't handle data migrations (add custom `op.execute()`)

#### Migration Naming Convention

```bash
# Use descriptive, lowercase names with underscores
PYTHONPATH=. uv run alembic revision --autogenerate -m "add_user_preferences_table"
PYTHONPATH=. uv run alembic revision --autogenerate -m "add_index_on_episodes_created_at"

# For feature-specific migrations, use prefixes:
# agent_*    - Agent system changes
# billing_*  - Billing feature changes
# schema_*   - Schema system changes
# litellm_*  - LLM provider changes
```

#### Migration File Structure

```python
# alembic/versions/agent_004_add_tool_results.py
"""Add tool execution results table

Revision ID: agent_004
Revises: agent_003
Create Date: 2026-01-13

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = 'agent_004'
down_revision = 'agent_003'  # Previous migration ID
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Apply changes
    op.create_table(
        'tool_results',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('step_id', sa.String(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['step_id'], ['plan_steps.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tool_results_step_id', 'tool_results', ['step_id'])

def downgrade() -> None:
    # Revert changes (must be reverse of upgrade)
    op.drop_index('ix_tool_results_step_id')
    op.drop_table('tool_results')
```

#### Common Migration Patterns

**Add new table:**

```python
def upgrade() -> None:
    op.create_table(
        'new_table',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )
```

**Add new column (nullable for existing data):**

```python
def upgrade() -> None:
    op.add_column('users', sa.Column('bio', sa.String(), nullable=True))
```

**Add new column with default value:**

```python
def upgrade() -> None:
    # First add as nullable
    op.add_column('users', sa.Column('status', sa.String(), nullable=True))
    # Update existing rows
    op.execute("UPDATE users SET status = 'active' WHERE status IS NULL")
    # Then make NOT NULL
    op.alter_column('users', 'status', nullable=False)
```

**Rename column (NOT detected by autogenerate):**

```python
def upgrade() -> None:
    op.alter_column('table_name', 'old_name', new_column_name='new_name')
```

**Add index:**

```python
def upgrade() -> None:
    op.create_index('ix_table_column', 'table_name', ['column_name'])
```

**Add foreign key:**

```python
def upgrade() -> None:
    op.create_foreign_key(
        'fk_table_other_id',
        'table_name', 'other_table',
        ['other_id'], ['id']
    )
```

**Data migration (with schema change):**

```python
def upgrade() -> None:
    # Add new column
    op.add_column('users', sa.Column('full_name', sa.String(), nullable=True))

    # Migrate data from old columns
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=op.get_bind())
    session = Session()
    session.execute(
        "UPDATE users SET full_name = first_name || ' ' || last_name"
    )
    session.commit()

    # Make column required
    op.alter_column('users', 'full_name', nullable=True)
```

#### Testing Migrations

**Test upgrade and downgrade:**

```bash
# Create test database
export DATABASE_URL="postgresql://user:pass@localhost:5432/test_db"

# Upgrade to specific version
PYTHONPATH=. uv run alembic upgrade agent_003

# Check current version
PYTHONPATH=. uv run alembic current

# Downgrade one step
PYTHONPATH=. uv run alembic downgrade -1

# Upgrade to head
PYTHONPATH=. uv run alembic upgrade head
```

**Test with auto-recovery (simulate missing alembic_version):**

```bash
# Simulate missing version table
docker exec memstack-postgres psql -U postgres -d memstack -c "DROP TABLE IF EXISTS alembic_version"

# Restart backend - should auto-recover
make dev-backend
```

#### Troubleshooting

**Migration hangs at startup:**

- Check if `alembic_version` table exists
- Verify tables match expected migration state
- Use auto-recovery: delete `alembic_version`, restart backend
- Manual fix: stamp with correct revision
  ```sql
  CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY);
  INSERT INTO alembic_version (version_num) VALUES ('agent_004');
  ```

**Autogenerate shows no changes:**

- Verify you modified the correct model file
- Run `PYTHONPATH=. uv run alembic revision --autogenerate -m "test"` to debug
- Check `alembic/env.py` includes your model's `Base.metadata`

**Downgrade fails:**

- Ensure `downgrade()` is the inverse of `upgrade()`
- Some operations (like `DROP COLUMN`) are not reversible safely
- Test downgrades on a copy of production data first

## OpenSpec Workflow

This project uses OpenSpec for spec-driven development. See `openspec/AGENTS.md` for full details.

**Quick checklist**:

1. Check existing specs: `openspec list --specs`
2. Check active changes: `openspec list`
3. Create proposal for new features (not bug fixes)
4. Validate: `openspec validate <change-id> --strict`
5. Implement after approval
6. Archive after deployment: `openspec archive <change-id> --yes`

## Important Notes

- **Multi-tenancy**: Always scope queries by `project_id` or `tenant_id`
- **Async I/O**: All database/HTTP operations must be async
- **API Key format**: `ms_sk_` + 64 hex chars, stored as SHA256 hash
- **Neo4j is critical**: Core knowledge graph functionality requires Neo4j 5.26+
- **Test coverage**: Must maintain 80%+ overall coverage
- **Code style**: 100 char line length, Ruff formatting
- **Agent state**: Agent conversations are stateful; use conversation_id for continuity
- **SSE connections**: Frontend must handle SSE disconnection gracefully
- **Workflow patterns**: Patterns are tenant-scoped, shared across projects

## Active Technologies

- **Backend**: Python 3.12+, FastAPI 0.110+, Pydantic 2.5+
- **Frontend**: React 19.2+, TypeScript 5.9+, Vite 7.3+, Zustand 5.0+
- **Agent**: Self-developed ReAct Core, LangChain 0.3+ (LLM utilities only)
- **Knowledge Graph**: Native Graph Adapter (自研), Neo4j 5.26+
- **Task Scheduler**: Temporal.io (enterprise-grade workflow orchestration)
- **LLM**: LiteLLM 1.0+ (multi-provider: Gemini, Qwen, Deepseek, ZhipuAI, OpenAI)
- **Databases**: Neo4j 5.26+, PostgreSQL 16+, Redis 7+

## Frontend Refactoring (Completed 2026-01-28)

The frontend has undergone a comprehensive refactoring following React 19.2+ best practices. **Status: 100% Complete** ✅

### Completed Improvements

| Phase | Tasks | Status |
|-------|-------|--------|
| **Foundation** | ErrorBoundary, Barrel exports, React.memo, Type fixes | ✅ 100% |
| **State Management** | Zustand persist, DevTools, Store splitting | ✅ 100% |
| **Performance** | Virtual scrolling, useCallback, useMemo | ✅ 90% |
| **API Layer** | Unified HTTP client, Retry logic, Cache, Deduplication | ✅ 100% |
| **Type Safety** | Removed `any` types, Shared type exports | ✅ 90% |
| **Components** | Memo optimization, Custom hooks | ✅ 90% |
| **Error Handling** | Route-level ErrorBoundaries | ✅ 100% |
| **Accessibility** | ARIA labels, Keyboard navigation | ✅ 100% |
| **Documentation** | JSDoc for stores, services, components | ✅ 90% |
| **Directory Structure** | Feature-based organization (shared, tenant, project, graph) | ✅ 100% |

### Key Features Added

**Developer Experience:**
- ✅ Zustand DevTools for all 15 stores (development mode only)
- ✅ Comprehensive JSDoc documentation (150+ functions/components)
- ✅ Environment-aware logger utility (production-safe)
- ✅ Component directory organized by feature scope

**Performance:**
- ✅ Virtual scrolling for MessageList, EntitiesList, CommunitiesList
- ✅ React.memo on critical components (WorkPlanCard, ToolExecutionCard, etc.)
- ✅ useCallback/useMemo optimizations for expensive computations
- ✅ HTTP request caching and deduplication

**Reliability:**
- ✅ Route-level ErrorBoundaries (Tenant, Project, Agent, Schema contexts)
- ✅ Exponential backoff retry logic for failed HTTP requests
- ✅ Unified ApiError type system

**Accessibility:**
- ✅ 80+ ARIA labels on buttons, inputs, and interactive elements
- ✅ Full keyboard navigation support for dropdowns and menus
- ✅ 16 E2E accessibility tests

### Component Architecture

```
web/src/components/
├── shared/          # Truly shared, scope-independent components
│   ├── layouts/     # AppLayout, ResponsiveLayout, Layout
│   ├── modals/      # DeleteConfirmationModal
│   └── ui/          # LanguageSwitcher, NotificationPanel, ThemeToggle, WorkspaceSwitcher
├── agent/           # Agent-specific components (50+ files)
├── tenant/          # Tenant-scoped components
├── project/         # Project-scoped components
├── graph/           # Knowledge graph visualization
└── common/          # Utility components (ErrorBoundary, VirtualGrid, etc.)
```

### Testing Coverage

| Test Type | Files | Tests |
|-----------|-------|-------|
| Unit Tests | `logger.test.ts` | 10 passing |
| E2E Tests | `auth.spec.ts`, `accessibility.spec.ts` | 22 passing |

## Recent Changes

- **Frontend Refactoring Complete** (2026-01-28): Comprehensive frontend modernization
  - All 10 refactoring phases completed
  - Performance: Virtual scrolling, memo optimization, HTTP caching
  - Reliability: Route-level ErrorBoundaries, retry logic
  - Accessibility: ARIA labels, keyboard navigation
  - Documentation: 150+ JSDoc comments
- **005-temporal-integration** (2026-01-17): Temporal.io enterprise task scheduling system
  - Episode、Entity、Community processing workflows and activities
  - Docker Compose Temporal server and UI configuration
  - Worker entry point (`src/worker_temporal.py`)
- **Bug Fixes** (2026-01-17): Fixed 11 critical issues in Agent tools and knowledge graph extraction
- **004-native-graph-adapter**: Self-developed knowledge graph engine replacing Graphiti dependency
- **003-react-agent**: Added React Agent System with multi-level thinking, workflow pattern learning, tool composition, and structured output
- **LiteLLM Integration**: Multi-provider LLM support (Gemini, Qwen, Deepseek, ZhipuAI, OpenAI)
- **SSE Streaming**: Real-time agent responses via Server-Sent Events
- **Frontend Overhaul**: Complete React 19.2+ frontend with Ant Design 6.1+ and Zustand state management
