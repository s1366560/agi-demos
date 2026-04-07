# AGENTS.md

This file provides guidance to AI coding assistants (Copilot, Claude, Cursor, Gemini, etc.) when working with code in this repository.

**MemStack** - 企业级 AI 记忆云平台 (Enterprise AI Memory Cloud Platform)

A full-stack Python backend with React frontend, following **DDD + Hexagonal Architecture**.

## AI Assistant Guidelines

### Core Philosophy
1. **Agent-First**: Delegate to specialized agents for complex work
2. **Parallel Execution**: Use Task tool with multiple agents when possible
3. **Plan Before Execute**: Use Plan Mode for complex operations
4. **Test-Driven**: Write tests before implementation
5. **Security-First**: Never compromise on security

### Available Custom Agents

| Agent | Purpose |
|-------|---------|
| `planner` | Feature implementation planning |
| `architect` | System design and architecture |
| `tdd-guide` | Test-driven development |
| `code-reviewer` | Code review for quality/security |
| `security-reviewer` | Security vulnerability analysis |
| `build-error-resolver` | Build error resolution |
| `go-build-resolver` | Go build/vet error resolution |
| `python-reviewer` | Python code review (PEP 8, type hints) |
| `go-reviewer` | Go code review (idiomatic patterns) |
| `database-reviewer` | PostgreSQL query/schema review |
| `e2e-runner` | Playwright E2E testing |
| `refactor-cleaner` | Dead code cleanup |
| `doc-updater` | Documentation updates |

### Privacy & Security
- Always redact logs; never paste secrets (API keys/tokens/passwords/JWTs)
- Review output before sharing - remove any sensitive data
- Run `security-reviewer` agent for code handling user input, auth, or sensitive data

### Code Style Preferences
- No emojis in code, comments, or documentation
- Prefer immutability - never mutate objects or arrays
- Many small files over few large files (200-400 lines typical, 800 max)
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`

### Success Metrics
- All tests pass (80%+ coverage)
- No security vulnerabilities
- Code is readable and maintainable
- User requirements are met

## Quick Start

```bash
make init          # 首次设置: 安装依赖 + 启动基础设施 + 初始化数据库
make dev           # 启动所有后端服务 (API + workers + infra)
make dev-web       # 启动前端 (另开终端, 端口 3000)
make status        # 检查服务状态
```

**环境重置 / Environment Reset:**
```bash
make stop          # 停止所有服务 (alias: dev-stop)
make restart       # 快速重启服务
make reset         # 完整重置 (停止 + 清理 Docker + 清理缓存)
make fresh         # 从零开始 (reset + init + dev)
```

**默认凭据 / Default Credentials** (auto-created after `make dev`):
| User | Email | Password |
|------|-------|----------|
| Admin | `admin@memstack.ai` | `adminpassword` |
| User | `user@memstack.ai` | `userpassword` |

## 常用命令 / Development Commands

### 开发服务 / Development Services

| Command | Description |
|---------|-------------|
| `make dev` | Start all backend services (API + workers + infra) |
| `make stop` | Stop all services (alias: dev-stop) |
| `make logs` | View all logs (alias: dev-logs) |
| `make infra` | Start infrastructure only (alias: dev-infra) |
| `make dev-backend` | Start API server only (foreground, port 8000) |
| `make dev-worker` | Start data processing worker only |
| `make dev-agent-worker` | Start Agent worker only |
| `make dev-mcp-worker` | Start MCP worker only |
| `make dev-web` | Start web frontend (port 3000) |
| `make status` | Show all service status |

### 测试 / Testing

| Command | Description |
|---------|-------------|
| `make test` | Run all tests |
| `make test-unit` | Unit tests only (fast) |
| `make test-integration` | Integration tests only |
| `make test-coverage` | Run with coverage report (80%+ target) |
| `make test-watch` | Watch mode testing |

```bash
# Run single test file
uv run pytest src/tests/unit/test_memory_service.py -v

# Run single test function
uv run pytest src/tests/unit/test_memory_service.py::TestMemoryService::test_create -v

# Run by marker
uv run pytest src/tests/ -m "unit" -v
uv run pytest src/tests/ -m "integration" -v
```

### 代码质量 / Code Quality

| Command | Description |
|---------|-------------|
| `make format` | Format all code (ruff + eslint) |
| `make lint` | Lint all code (ruff + mypy + pyright + eslint) |
| `make check` | Run all checks (format + lint + test) |
| `make ci` | Run CI pipeline (lint + test + build) |
| `make type-check` | Run all type checkers (mypy + pyright) |
| `make type-check-mypy` | Run mypy only |
| `make type-check-pyright` | Run pyright only |
| `make hooks-install` | Install git pre-commit hooks |

### 数据库 / Database

| Command | Description |
|---------|-------------|
| `make db-init` | Initialize database |
| `make db-reset` | Reset database (WARNING: deletes all data) |
| `make db-migrate` | Run Alembic migrations |
| `make db-migrate-new` | Generate new migration file |
| `make db-status` | Show migration status |

```bash
# Alembic commands
PYTHONPATH=. uv run alembic current                    # Show current version
PYTHONPATH=. uv run alembic history                    # Show migration history
PYTHONPATH=. uv run alembic upgrade head               # Apply all migrations
PYTHONPATH=. uv run alembic downgrade -1               # Rollback one step
PYTHONPATH=. uv run alembic revision --autogenerate -m "description"  # Generate migration
```

### Docker & Sandbox

| Command | Description |
|---------|-------------|
| `make docker-up` | Start all Docker services |
| `make docker-down` | Stop Docker services |
| `make docker-clean` | Clean containers, volumes, orphans |
| `make sandbox-build` | Build sandbox image |
| `make sandbox-run` | Start sandbox (VNC=x11vnc for fallback) |
| `make sandbox-stop` | Stop sandbox |
| `make sandbox-status` | Show sandbox status |
| `make sandbox-shell` | Open shell (ROOT=1 for root) |
| `make sandbox-test` | Run validation tests |

### 可观测性 / Observability

| Command | Description |
|---------|-------------|
| `make obs-start` | Start observability (Jaeger, OTel, Prometheus, Grafana) |
| `make obs-stop` | Stop observability services |
| `make obs-ui` | Show observability UI URLs |

## 架构概览 / Architecture Overview

```
src/
├── domain/                    # 核心业务逻辑 (无外部依赖)
│   ├── model/                # Domain entities (8 modules)
│   │   ├── agent/           # Conversation, Plan, Skill, SubAgent, WorkPlan, Message, HITLRequest
│   │   ├── memory/          # Memory, Entity, Episode, Community
│   │   ├── project/         # Project, SandboxConfig
│   │   ├── sandbox/         # ProjectSandbox, ResourcePool, StateMachine
│   │   ├── artifact/        # Artifact with status/category enums
│   │   ├── mcp/             # MCPServer, MCPTool, MCPServerConfig
│   │   ├── auth/            # User, ApiKey, Permissions
│   │   └── tenant/          # Tenant
│   ├── ports/               # Repository & service interfaces (dependency inversion)
│   └── exceptions/          # Domain exceptions
│
├── application/              # Application orchestration layer
│   ├── services/            # Application services
│   ├── use_cases/           # Use case implementations
│   ├── schemas/             # Request/response DTOs
│   └── tasks/               # Background task handlers
│
├── infrastructure/           # External implementations (adapters)
│   ├── adapters/
│   │   ├── primary/         # Driving adapters (FastAPI routers: 31 modules, 50+ endpoints)
│   │   └── secondary/       # Driven adapters (persistence, workflow, external APIs)
│   ├── agent/               # ReAct Agent system (4-layer architecture)
│   ├── llm/                 # LiteLLM unified client
│   ├── graph/               # Neo4j knowledge graph
│   ├── mcp/                 # Model Context Protocol
│   └── security/            # Authentication & authorization
│
└── configuration/            # Config and DI container

web/src/
├── components/              # React components (agent/, artifact/, graph/, mcp/, skill/, etc.)
├── pages/                   # Page components (25+ pages)
├── stores/                  # Zustand state management
├── services/                # API service clients
├── hooks/                   # Custom React hooks
└── types/                   # TypeScript type definitions
```

## Agent 四层架构 / Agent 4-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│  L4: Agent (ReAct 推理循环 / ReAct Reasoning Loop)       │
│  ├─ SessionProcessor: Think → Act → Observe cycle       │
│  ├─ DoomLoopDetector: Stuck detection                   │
│  └─ CostTracker: Token/cost tracking                    │
├─────────────────────────────────────────────────────────┤
│  L3: SubAgent (专业化代理 / Specialized Agents)          │
│  ├─ SubAgentOrchestrator: Routes to specialized agents  │
│  ├─ SubAgentRouter: Semantic matching                   │
│  └─ SubAgentExecutor: SubAgent execution                │
├─────────────────────────────────────────────────────────┤
│  L2: Skill (声明式工具组合 / Declarative Compositions)   │
│  ├─ SkillOrchestrator: Skill matching and routing       │
│  ├─ SkillExecutor: Skill execution                      │
│  └─ Trigger modes: keyword / semantic / hybrid          │
├─────────────────────────────────────────────────────────┤
│  L1: Tool (原子能力 / Atomic Capabilities)               │
│  ├─ TerminalTool: Shell command execution               │
│  ├─ DesktopTool: Desktop/UI interaction                 │
│  ├─ WebSearchTool / WebScrapeTool: Web operations       │
│  ├─ PlanEnterTool / PlanUpdateTool / PlanExitTool       │
│  ├─ ClarificationTool / DecisionTool: User interaction  │
│  ├─ GetEnvVarTool / RequestEnvVarTool: Environment      │
│  └─ SandboxMCPToolWrapper: MCP tool wrapper             │
└─────────────────────────────────────────────────────────┘
```

**Execution Router** decides path based on confidence scoring (0.0-1.0):
```
DIRECT_SKILL → SUBAGENT → PLAN_MODE → REACT_LOOP
```

## Tool-to-Event 管道 / Tool-to-Event Pipeline

### ToolDefinition 包装机制 / ToolDefinition Wrapping

Tool instances (e.g. `TodoWriteTool`, `TerminalTool`) are **NOT** used directly by the
SessionProcessor. They are converted to `ToolDefinition` dataclass wrappers by
`tool_converter.py`:

```
TodoWriteTool instance
    ↓ convert_tools()
ToolDefinition(
    name="todowrite",
    execute=closure_wrapper(tool.execute),   # Only the execute() method is wrapped
    _tool_instance=TodoWriteTool,            # Original instance stored here
)
    ↓ SessionProcessor.tools dict
processor.tools["todowrite"] → ToolDefinition (NOT TodoWriteTool)
```

**CRITICAL**: To access tool-specific methods (e.g. `consume_pending_events()`),
use `tool_def._tool_instance`, NOT `tool_def` directly. `tool_def` is a
`ToolDefinition` with only `name/description/parameters/execute/permission` fields.

### SSE 事件发射流程 / SSE Event Emission Flow

Tools emit side-effect events (e.g. task updates) through a **pending events pattern**:

```
1. Tool.execute()       → appends events to self._pending_events
2. Processor            → after execute, calls tool_instance.consume_pending_events()
3. Processor            → yields domain events (AgentTaskListUpdatedEvent, etc.)
4. ReActAgent.stream()  → EventConverter.convert() → event dict
5. execution.py         → publishes to Redis Stream (agent:events:{conversation_id})
6. agent_service.py     → connect_chat_stream() reads from Redis, yields to WS bridge
7. chat_handler.py      → broadcasts via WebSocket to frontend
8. Frontend             → routeToHandler() dispatches to Zustand store handlers
```

### Event 类型参考 / Event Type Reference

| Event Type | Source | Purpose |
|------------|--------|---------|
| `task_list_updated` | todowrite (replace/add) | Full task list sync to frontend |
| `task_updated` | todowrite (update) | Single task status change |
| `task_start` | Processor (from task_list_updated) | Timeline: task execution started |
| `task_complete` | Processor (from task_updated) | Timeline: task execution finished |
| `artifact_created` | Processor (_process_tool_artifacts) | Artifact upload initiated |
| `artifact_ready` | Processor (threaded upload complete) | Artifact available for download |

### 添加新工具事件的检查清单 / Checklist for Adding New Tool Events

When a tool needs to emit custom SSE events to the frontend:

1. **Tool class**: Add `_pending_events` list and `consume_pending_events()` method
2. **Tool.execute()**: Append event dicts to `self._pending_events` after DB commit
3. **tool_converter.py**: Already handled -- `_tool_instance` is set automatically
4. **processor.py**: Add a post-execute block (like the todowrite block) that:
   - Gets `tool_instance` via `getattr(tool_def, "_tool_instance", None)`
   - Calls `tool_instance.consume_pending_events()`
   - Yields appropriate `AgentDomainEvent` subclasses
5. **agent_events.py**: Define new `AgentDomainEvent` subclass with `to_event_dict()`
6. **types.py**: Add new `AgentEventType` enum value
7. **converter.py**: Add transformation in `_apply_transformations()` if needed
   (events without explicit handling pass through via `to_event_dict()` unchanged)
8. **Frontend agentService.ts**: Add case in `routeToHandler()` switch
9. **Frontend streamEventHandlers.ts**: Add handler (e.g. `onMyEvent`)
10. **Frontend types**: Add event data type and handler interface member

### Logging 注意事项 / Logging Notes

- `main.py` has `logging.basicConfig()` at module level for application-wide logging
- All `src.*` module loggers write to stderr, captured by uvicorn's output redirect
- `LOG_LEVEL` env var controls the level (default: INFO)
- Ray Actor code runs in Docker containers with their own code copy -- local code
  changes are NOT reflected until the actor image is rebuilt
- **Development Mode**: Use `make ray-up-dev` to start Ray with live code reloading via volume mounts
- Use `make ray-reload` to restart Ray services after code changes (faster than rebuild)
- Use `docker logs memstack-ray-worker` or Ray worker log files for actor-side debugging

## MCP & Sandbox 系统 / MCP & Sandbox System

### Two Sandbox Adapters

| Adapter | Use Case | Communication |
|---------|----------|---------------|
| `MCPSandboxAdapter` | Cloud Docker containers | WebSocket |
| `LocalSandboxAdapter` | User's local machine | WebSocket + ngrok/Cloudflare tunnel |

### MCP Tools (30+)

| Category | Tools |
|----------|-------|
| **File Operations** | `read`, `write`, `edit`, `glob`, `grep`, `list`, `patch` |
| **Code Intelligence** | `ast_parse`, `ast_find_symbols`, `find_definition`, `find_references`, `call_graph` |
| **Editing** | `edit_by_ast`, `batch_edit`, `preview_edit` |
| **Testing** | `generate_tests`, `run_tests`, `analyze_coverage` |
| **Git** | `git_diff`, `git_log`, `generate_commit` |
| **Terminal/Desktop** | `start_terminal`, `start_desktop` (ttyd + noVNC) |

## 后台工作流 / Background Workflows

Background workflows run as asyncio tasks with retry and status tracking via TaskLog.

**HITL (Human-in-the-Loop) Types:**
- `clarification`: Request user clarification
- `decision`: Request user decision
- `env_var`: Request environment variable
- `permission`: Request tool permission

## 编码规范 / Coding Standards

### Python (Backend)

**Formatting & Linting:**
- Line length: 100 characters
- Formatter: `ruff format`
- Linter: `ruff check` (E, F, I, N, UP, B, C4, SIM, RUF, ANN, C901, PLR091 rules)
- Type checker: `mypy` (strict mode, tests/alembic/legacy excluded)
- Type checker: `pyright` (strict mode, 40+ explicit error rules, same excludes as mypy)

**Commands:**
```bash
make format-backend    # Format Python code
make lint-backend      # Lint Python code (ruff + mypy + pyright)
make type-check-mypy   # Run mypy only
make type-check-pyright # Run pyright only
uv run ruff check src/ # Check specific directory
uv run ruff format src/ --check  # Check formatting without changes
```

**Pre-commit Hook (type safety enforcement):**
- Runs automatically on `git commit` (after `make hooks-install`)
- Checks staged Python files with `ruff check` + `pyright`
- Only checks files in `src/`, `sdk/`, `scripts/` (excludes tests, alembic, memstack_agent)
- See `docs/TYPE_SAFETY.md` for full type safety guidelines

**Naming Conventions:**
| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `UserService`, `SqlUserRepository` |
| Functions/variables | snake_case | `create_user`, `user_id` |
| Constants | UPPER_SNAKE_CASE | `MAX_RETRIES`, `DEFAULT_TIMEOUT` |
| Private members | _leading_underscore | `_internal_method`, `_session` |

**Import Order (Auto-enforced by Ruff):**
```python
# 1. Future imports
from __future__ import annotations

# 2. Standard library
import logging
from datetime import datetime
from typing import Optional

# 3. Third-party
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# 4. First-party (src.*)
from src.domain.model.user import User
from src.domain.ports.repositories import UserRepository

# 5. Local/relative
from .models import UserModel
```

**Domain Model Template:**
```python
"""Domain model for Entity."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass(kw_only=True)
class Entity:
    """Represents an entity in the system.
    
    Attributes:
        id: Unique identifier.
        name: Entity name.
        created_at: Creation timestamp.
    """
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def update_name(self, new_name: str) -> None:
        """Update the entity name."""
        if not new_name:
            raise ValueError("Name cannot be empty")
        self.name = new_name
```

**Repository Template:**
```python
"""Repository implementation for Entity."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.entity import Entity
from src.domain.ports.repositories import EntityRepository
from src.infrastructure.adapters.secondary.persistence.base import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import EntityModel


class SqlEntityRepository(BaseRepository[Entity, EntityModel], EntityRepository):
    """SQLAlchemy implementation of EntityRepository."""

    _model_class = EntityModel

    async def find_by_id(self, entity_id: str) -> Optional[Entity]:
        """Find entity by ID."""
        query = select(EntityModel).where(EntityModel.id == entity_id)
        result = await self._session.execute(query)
        db_entity = result.scalar_one_or_none()
        return self._to_domain(db_entity) if db_entity else None

    def _to_domain(self, db_entity: EntityModel) -> Entity:
        """Convert database model to domain entity."""
        return Entity(id=db_entity.id, name=db_entity.name)

    def _to_db(self, entity: Entity) -> EntityModel:
        """Convert domain entity to database model."""
        return EntityModel(id=entity.id, name=entity.name)
```

**Service Template:**
```python
"""Application service for Entity operations."""
import logging
from typing import Optional

from src.domain.model.entity import Entity
from src.domain.ports.repositories import EntityRepository

logger = logging.getLogger(__name__)


class EntityService:
    """Service for managing Entity lifecycle."""

    def __init__(self, entity_repo: EntityRepository) -> None:
        self._entity_repo = entity_repo

    async def create(self, name: str) -> Entity:
        """Create a new entity."""
        if not name:
            raise ValueError("Name cannot be empty")
        
        entity = Entity(name=name)
        await self._entity_repo.save(entity)
        logger.info(f"Created entity {entity.id}")
        return entity

    async def get_by_id(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        return await self._entity_repo.find_by_id(entity_id)
```

**CRITICAL: DI Container & DB Session Patterns**

The application uses a **global** `DIContainer` instance at `request.app.state.container` initialized at startup with `db=None`. This global container is for singletons (Neo4j client, Redis, graph service) that do NOT need per-request DB sessions. **NEVER** use the global container to create services that require a DB session -- the session will be `None` and cause `AttributeError: 'NoneType' object has no attribute 'execute'`.

Two patterns exist for accessing the database in API endpoints:

**Pattern A: Direct DB injection (preferred for most endpoints)**
```python
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, Request
from src.infrastructure.adapters.secondary.persistence.database import get_db
from .utils import get_container_with_db

@router.get("/items")
async def list_items(
    request: Request,
    db: AsyncSession = Depends(get_db),  # Per-request session
):
    container = get_container_with_db(request, db)  # Scoped DIContainer with real session
    service = container.some_service()  # Has db access
    return await service.list()
```

`get_container_with_db(request, db)` creates a new `DIContainer` with the request's DB session while preserving graph_service and redis_client from the global container. Defined in `src/infrastructure/adapters/primary/web/routers/agent/utils.py`.

**Pattern B: Dependency function (for focused services)**
```python
# In dependencies/__init__.py
async def get_plan_coordinator(
    db: AsyncSession = Depends(get_db),
):
    """Builds service directly with per-request DB session."""
    return PlanCoordinator(
        plan_repo=SqlPlanRepository(db),
        workplan_repo=SqlWorkPlanRepository(db),
    )

# In router
@router.post("/plans")
async def create_plan(
    coordinator=Depends(get_plan_coordinator),  # FastAPI chains Depends(get_db)
):
    return await coordinator.create(...)
```

**Key rules:**
| Rule | Detail |
|------|--------|
| `request.app.state.container` | Global, `_db=None`. Only use for singletons (neo4j_client, graph_service, redis) |
| `get_container_with_db(request, db)` | Creates scoped DIContainer with real session. Use in endpoints needing full container |
| `Depends(get_db)` | Provides per-request `AsyncSession` via `async_session_factory()`. Auto-closed after request |
| `DIContainer.with_db(db)` | Alternative: `request.app.state.container.with_db(db)` returns a cloned container with session |
| Repository constructors | Always take `AsyncSession` as first arg: `SqlXxxRepository(db)` |
| Commit responsibility | Caller (endpoint) is responsible for `await db.commit()`. Sessions auto-close but do NOT auto-commit |

**Common mistake:**
```python
# WRONG - global container has db=None
def get_my_service(request: Request):
    return request.app.state.container.my_service()  # my_service's repo will have _session=None

# CORRECT - inject per-request session
async def get_my_service(db: AsyncSession = Depends(get_db)):
    return MyService(repo=SqlMyRepository(db))
```

### TypeScript/React (Frontend)

**Formatting & Linting:**
- Formatter: `prettier` (100 char line width, single quotes, semicolons)
- Linter: `eslint` with TypeScript + React plugins
- Import sorting: `eslint-plugin-import` (auto-sorted)

**Commands:**
```bash
pnpm format        # Format all files
pnpm format:check  # Check formatting without changes
pnpm lint          # Lint and auto-fix
```

**Naming Conventions:**
| Type | Convention | Example |
|------|------------|---------|
| Components | PascalCase file | `MessageBubble.tsx` |
| Hooks | use prefix | `useAgentStore` |
| Services | camelCase | `agentService.ts` |
| Stores | Store suffix | `agentStore.ts` |
| Props interfaces | ComponentNameProps | `MessageBubbleProps` |

**Import Order (Auto-enforced by ESLint):**
```tsx
// 1. React and React ecosystem
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

// 2. External libraries
import { Button, Modal } from 'antd';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';

// 3. Internal modules (stores → services → hooks)
import { useAuthStore } from '@/stores/auth';
import { projectService } from '@/services/projectService';
import { useDebounce } from '@/hooks/useDebounce';

// 4. Components
import { EmptyState } from '@/components/common/EmptyState';

// 5. Types (type-only imports)
import type { Project } from '@/types/project';

// 6. Styles (if any)
import './styles.css';
```

**⚠️ CRITICAL: Zustand useShallow Pattern**
```tsx
// ✅ CORRECT - Object selectors MUST use useShallow
import { useShallow } from 'zustand/react/shallow';

const { messages, isLoading } = useAgentStore(
  useShallow((state) => ({
    messages: state.messages,
    isLoading: state.isLoading,
  }))
);

// ❌ WRONG - Causes infinite re-render loop
const { messages, isLoading } = useAgentStore(
  (state) => ({ messages: state.messages, isLoading: state.isLoading })
);

// ✅ Single value selectors don't need useShallow
const messages = useAgentStore((state) => state.messages);
```

**Anti-Barrel Import:**
```tsx
// ❌ Avoid importing from index.ts
import { Button } from '@/components';

// ✅ Direct imports preferred
import { Button } from '@/components/ui/Button';
```

**⚠️ API Service Paths (httpClient baseURL):**
```tsx
// httpClient already sets baseURL: '/api/v1'
// All service paths MUST be relative to that base.

// ❌ WRONG - causes doubled prefix: /api/v1/api/v1/mcp/apps
const BASE_URL = '/api/v1/mcp/apps';

// ✅ CORRECT - resolves to /api/v1/mcp/apps
const BASE_URL = '/mcp/apps';
```

**⚠️ CRITICAL: Trailing Slashes on Collection Endpoints:**

FastAPI's `redirect_slashes` returns `307 Temporary Redirect` when a URL lacks
a trailing slash. In dev mode (Vite proxy on port 3000 → backend on port 8000),
the 307 `Location` header points to `http://localhost:8000/...` (cross-origin).
The browser strips the `Authorization` header on cross-origin redirects per HTTP spec,
causing a 401 → `clearAuthState()` → redirect to `/login`.

```tsx
// ❌ WRONG - triggers 307 redirect, strips auth header, causes login redirect
list: (params) => httpClient.get(BASE_URL, { params }),
create: (data) => httpClient.post(BASE_URL, data),

// ✅ CORRECT - direct hit, no redirect
list: (params) => httpClient.get(`${BASE_URL}/`, { params }),
create: (data) => httpClient.post(`${BASE_URL}/`, data),

// ✅ Paths with sub-resources are fine (no redirect)
getById: (id: string) => httpClient.get(`${BASE_URL}/${id}`),
```

**Rule**: Any `httpClient` call that hits a collection root (list/create) MUST
include a trailing slash. Calls with path segments (`/${id}`, `/${id}/action`)
are unaffected.

**Component Template:**
```tsx
import React from 'react';

import type { FC } from 'react';

export interface ComponentNameProps {
  /** Description of prop */
  title: string;
  /** Optional prop with default */
  disabled?: boolean;
}

export const ComponentName: FC<ComponentNameProps> = ({ title, disabled = false }) => {
  return <div className={disabled ? 'opacity-50' : ''}>{title}</div>;
};
```

**Store Template:**
```tsx
import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { exampleService } from '@/services/exampleService';
import { getErrorMessage } from '@/types/common';

interface ExampleState {
  // State
  items: Item[];
  loading: boolean;
  error: string | null;
  // Actions
  fetchItems: () => Promise<void>;
  reset: () => void;
}

export const useExampleStore = create<ExampleState>()(
  devtools(
    (set) => ({
      items: [],
      loading: false,
      error: null,

      fetchItems: async () => {
        set({ loading: true, error: null });
        try {
          const items = await exampleService.list();
          set({ items, loading: false });
        } catch (err) {
          set({ error: getErrorMessage(err), loading: false });
        }
      },

      reset: () => set({ items: [], loading: false, error: null }),
    }),
    { name: 'example-store' }
  )
);

// Selectors - single values don't need useShallow
export const useItems = () => useExampleStore((state) => state.items);
export const useExampleLoading = () => useExampleStore((state) => state.loading);

// Action selectors - MUST use useShallow for object returns
export const useExampleActions = () =>
  useExampleStore(useShallow((state) => ({ fetchItems: state.fetchItems, reset: state.reset })));
```

### Testing Conventions

**Python:**
```python
# File: test_{module}.py | Class: Test{Component} | Method: test_{scenario}_{expected}

@pytest.mark.unit
class TestUserService:
    async def test_create_user_success(self, db_session):
        # Arrange
        service = UserService(db_session)
        # Act
        user = await service.create("test@example.com")
        # Assert
        assert user.email == "test@example.com"
```
- Tests use `asyncio_mode = "auto"` - no need for `@pytest.mark.asyncio`
- Key fixtures: `db_session`, `test_user`, `test_project_db`, `authenticated_client`

**TypeScript:**
- Unit tests: `{Component}.test.tsx`
- E2E tests: `{feature}.spec.ts`

## 核心概念 / Core Domain Concepts

| Concept | Description |
|---------|-------------|
| **Episodes** | Discrete interactions containing content and metadata |
| **Memories** | Semantic memory extracted from episodes, stored in Neo4j |
| **Entities** | Real-world objects with attributes and relationships |
| **Projects** | Multi-tenant isolation units with independent knowledge graphs |
| **Skills** | Declarative tool compositions with trigger patterns |
| **SubAgents** | Specialized autonomous agents for specific task types |
| **API Keys** | Format: `ms_sk_` + 64 hex chars, stored as SHA256 hash |

## 关键文件 / Key File Locations

### Backend Entry Points
| File | Purpose |
|------|---------|
| `src/infrastructure/adapters/primary/web/main.py` | API entry point |
| `src/configuration/config.py` | Pydantic Settings |
| `src/configuration/di_container.py` | Dependency injection |

### Agent System
| File | Purpose |
|------|---------|
| `src/infrastructure/agent/core/react_agent.py` | ReAct Agent |
| `src/infrastructure/agent/processor/processor.py` | Session Processor (tool exec + event emission) |
| `src/infrastructure/agent/core/tool_converter.py` | Tool instance -> ToolDefinition conversion |
| `src/infrastructure/agent/tools/` | L1 Tools (todo_tools, terminal, etc.) |
| `src/infrastructure/agent/tools/todo_tools.py` | TodoRead/TodoWrite with pending events pattern |
| `src/infrastructure/agent/skill/orchestrator.py` | Skill Orchestrator |
| `src/infrastructure/agent/routing/router.py` | SubAgent Router |
| `src/infrastructure/agent/events/converter.py` | Domain event -> SSE dict conversion |
| `src/infrastructure/agent/actor/execution.py` | Actor event loop + Redis publication |
| `src/domain/events/agent_events.py` | Domain event classes |
| `src/domain/events/types.py` | AgentEventType enum |

### Knowledge Graph
| File | Purpose |
|------|---------|
| `src/infrastructure/graph/native_graph_adapter.py` | Native Graph Adapter |
| `src/infrastructure/graph/extraction/entity_extractor.py` | Entity Extractor |
| `src/infrastructure/graph/search/hybrid_search.py` | Hybrid Search |

### Frontend
| File | Purpose |
|------|---------|
| `web/src/App.tsx` | App entry |
| `web/src/pages/tenant/AgentWorkspace.tsx` | Agent Chat Page |
| `web/src/stores/agentV3.ts` | Agent Store |
| `web/src/services/agentService.ts` | Agent Service |

## API 测试 / API Testing

```bash
# Get API Key from logs
tail -50 logs/api.log | grep "API Key"

# Or login to get token
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@memstack.ai&password=adminpassword"

# API calls
export API_KEY="ms_sk_your_key_here"

curl -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/v1/projects

curl -X POST http://localhost:8000/api/v1/episodes \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "1", "content": "Test content"}'

# Agent chat (SSE streaming)
curl -N http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "conv-id", "message": "Hello", "project_id": "1"}'
```

**Service URLs:**
- Swagger UI: http://localhost:8000/docs
- Web Frontend: http://localhost:3000

## 环境变量 / Environment Variables

| Category | Variables | Description |
|----------|-----------|-------------|
| **API** | `API_HOST`, `API_PORT` | API server config |
| **Security** | `SECRET_KEY`, `LLM_ENCRYPTION_KEY` | Encryption keys |
| **Neo4j** | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Graph database |
| **PostgreSQL** | `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Metadata DB |
| **Redis** | `REDIS_HOST`, `REDIS_PORT` | Cache |
| **LLM** | `LLM_PROVIDER` | Provider: `gemini`, `dashscope`, `openai`, `deepseek` |
| **LLM Keys** | `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY` | API keys |
| **Sandbox** | `SANDBOX_DEFAULT_PROVIDER`, `SANDBOX_TIMEOUT_SECONDS` | Code execution |
| **MCP** | `MCP_ENABLED`, `MCP_DEFAULT_TIMEOUT` | MCP protocol |

## 技术栈 / Tech Stack

| Layer | Technologies |
|-------|--------------|
| **Backend** | Python 3.12+, FastAPI 0.104+, SQLAlchemy 2.0+, PostgreSQL 16+, Redis 7+, Neo4j 5.26+ |
| **Workflow** | asyncio + Ray Actors |
| **LLM** | LiteLLM (Gemini, Dashscope, Deepseek, OpenAI, Anthropic) |
| **Frontend** | React 19.2+, TypeScript 5.9+, Vite 7.3+, Ant Design 6.1+, Zustand 5.0+ |
| **Testing** | pytest 7.4+, Vitest, Playwright (80%+ coverage target) |

## 重要注意事项 / Important Notes

| Rule | Description |
|------|-------------|
| **Multi-tenancy** | Always scope queries by `project_id` or `tenant_id` |
| **Async I/O** | All database/HTTP operations must be async |
| **API Key format** | `ms_sk_` + 64 hex chars, stored as SHA256 hash |
| **Neo4j critical** | Core knowledge graph requires Neo4j 5.26+ |
| **Test coverage** | Must maintain 80%+ overall coverage |
| **Agent state** | Conversations are stateful; use `conversation_id` for continuity |
| **Zustand useShallow** | Object selectors MUST use `useShallow` to prevent infinite re-renders |
| **Never modify DB directly** | Always use Alembic migrations |
| **Alembic autogenerate** | Always use `--autogenerate`, then review generated migration |
| **DB session in endpoints** | Never use global container (`request.app.state.container`) for DB-dependent services. Use `get_container_with_db(request, db)` or `Depends(get_db)` for per-request sessions |
| **ToolDefinition wrapping** | `processor.tools[name]` is a `ToolDefinition`, NOT the original tool. Use `tool_def._tool_instance` to access tool-specific methods like `consume_pending_events()` |
| **Tool event pattern** | Tools emit side-effect events via `_pending_events` list + `consume_pending_events()`. The processor must explicitly consume and yield them after `tool_def.execute()` |
| **Logging** | `main.py` has `logging.basicConfig()`. Without it, all `src.*` loggers silently discard output. `LOG_LEVEL` env var controls level |
| **Ray Actor code** | Runs in Docker containers with baked-in images. Local code changes require image rebuild to take effect in actors. **Dev mode**: Use `make ray-up-dev` for live code reloading |
| **Trailing slashes** | Frontend service collection URLs (list/create) MUST include trailing slashes (`${BASE_URL}/`). Without them, FastAPI 307 redirects strip the Authorization header via cross-origin redirect (Vite 3000 → backend 8000), causing silent 401 → login redirect |

<!-- gitnexus:start -->
# GitNexus MCP

This project is indexed by GitNexus as **agi-demos** (26139 symbols, 67541 relationships, 300 execution flows).

## Always Start Here

1. **Read `gitnexus://repo/{name}/context`** — codebase overview + check index freshness
2. **Match your task to a skill below** and **read that skill file**
3. **Follow the skill's workflow and checklist**

> If step 1 warns the index is stale, run `npx gitnexus analyze` in the terminal first.

## Skills

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

Use `agent-browser` for web automation. Run `agent-browser --help` for all commands.

Core workflow:
1. `agent-browser open <url>` - Navigate to page
2. `agent-browser snapshot -i` - Get interactive elements with refs (@e1, @e2)
3. `agent-browser click @e1` / `fill @e2 "text"` - Interact using refs
4. Re-snapshot after page changes
