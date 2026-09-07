# src/configuration/

Configuration loading and dependency injection for the entire backend.

Last checked against code: 2026-09-07

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | Pydantic `Settings` class (~624 lines, 100+ env vars). `get_settings()` is `@lru_cache` singleton |
| `di_container.py` | Application infrastructure shell. Keeps scoped DB handles and shared infrastructure; no Agent business factories |
| `factories.py` | Factory functions for LLM clients and `NativeGraphAdapter` (Neo4j + embedding) |
| `ray_config.py` | Ray Actor configuration for distributed execution |
| `containers/` | 3 domain-specific sub-containers (see below) |

## containers/ Hierarchy

| Container | Domain | Key Factories |
|-----------|--------|---------------|
| `auth_container.py` | Auth | `user_repository()`, `api_key_repository()`, `tenant_repository()` |
| `agent_container.py` | Agent | `agent_service()`, `chat_use_case()`, `context_window_manager()` |
| `infra_container.py` | Infra | `redis_client`, `workflow_engine`, `storage_service()`, `sandbox_adapter()` |

## Config Loading

- `Settings` extends `BaseSettings` with `SettingsConfigDict(env_file=".env")`
- All fields use `alias="ENV_VAR_NAME"` for env var mapping
- `get_settings()` is cached via `@lru_cache` -- singleton across the process
- Sections: API, DB (Postgres pool/replica), Redis, Neo4j, LLM, Sandbox, Security, Alerting

## DI Container Pattern

- `DIContainer.__init__()` accepts `db`, `redis_client`, `session_factory`, and an optional shared `InfraContainer`
- Creates Auth and shared Infra containers in `__init__`; never assembles an Agent container
- `with_db(db)` returns a NEW `DIContainer` clone with the given session
- Business repositories and services resolve from declared V2 Providers under a generation lease, not through top-level DI delegates

## CRITICAL: DB Session Rules

- Global container at `app.state.container` has `db=None` -- only for singletons (redis, graph_service)
- Per-request: use `get_container_with_db(request, db)` or `container.with_db(db)` in endpoints
- Repository constructors always take `AsyncSession` as first arg
- Caller (endpoint) is responsible for `await db.commit()`

## Forbidden

- Never call `app.state.container.some_service()` for DB-dependent services
- Never modify `get_settings()` return value (cached singleton)
- Never instantiate `DIContainer` without propagating graph_service/redis from global
