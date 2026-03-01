# src/configuration/

Configuration loading and dependency injection for the entire backend.

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | Pydantic `Settings` class (~450 lines, 100+ env vars). `get_settings()` is `@lru_cache` singleton |
| `di_container.py` | `DIContainer` class (~450 lines). Composes 7 sub-containers, delegates all factory methods |
| `factories.py` | Factory functions for LLM clients and `NativeGraphAdapter` (Neo4j + embedding) |
| `ray_config.py` | Ray Actor configuration for distributed execution |
| `containers/` | 7 domain-specific sub-containers (see below) |

## containers/ Hierarchy

| Container | Domain | Key Factories |
|-----------|--------|---------------|
| `auth_container.py` | Auth | `user_repository()`, `api_key_repository()`, `tenant_repository()` |
| `memory_container.py` | Memory | `memory_repository()`, `search_service()` |
| `agent_container.py` | Agent | `agent_service()`, `chat_use_case()`, `context_window_manager()` |
| `project_container.py` | Project | `project_service()`, `project_repository()` |
| `task_container.py` | Task | `task_repository()`, `task_service()` |
| `sandbox_container.py` | Sandbox | `sandbox_orchestrator()`, `sandbox_resource_pool()` |
| `infra_container.py` | Infra | `redis_client`, `workflow_engine`, `storage_service()`, `sandbox_adapter()` |

## Config Loading

- `Settings` extends `BaseSettings` with `SettingsConfigDict(env_file=".env")`
- All fields use `alias="ENV_VAR_NAME"` for env var mapping
- `get_settings()` is cached via `@lru_cache` -- singleton across the process
- Sections: API, DB (Postgres pool/replica), Redis, Neo4j, LLM, Sandbox, Security, Alerting

## DI Container Pattern

- `DIContainer.__init__()` accepts `db`, `graph_service`, `redis_client`, `session_factory`, `workflow_engine`
- Creates all 7 sub-containers in `__init__`, passing dependencies down
- `with_db(db)` returns a NEW `DIContainer` clone with the given session
- Public methods delegate to sub-containers: `self._auth.user_repository()`, `self._agent.agent_service()`, etc.

## CRITICAL: DB Session Rules

- Global container at `app.state.container` has `db=None` -- only for singletons (redis, graph_service)
- Per-request: use `get_container_with_db(request, db)` or `container.with_db(db)` in endpoints
- Repository constructors always take `AsyncSession` as first arg
- Caller (endpoint) is responsible for `await db.commit()`

## Forbidden

- Never call `app.state.container.some_service()` for DB-dependent services
- Never modify `get_settings()` return value (cached singleton)
- Never instantiate `DIContainer` without propagating graph_service/redis from global
