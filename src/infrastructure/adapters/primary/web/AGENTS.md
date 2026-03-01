# web/ -- FastAPI Application Layer

## Purpose
Application factory, startup/shutdown orchestration, middleware, and dependency wiring.

## Key Files
- `main.py` -- `create_app()` factory + `lifespan()` async context manager
- `middleware/exception_handlers.py` -- domain exception to HTTP mapping (565 lines)
- `dependencies.py` -- simple `request.app.state` accessors (graphiti, graph_service, workflow_engine)
- `dependencies/auth_dependencies.py` -- `get_current_user`, token validation
- `dependencies/authorization.py` -- role/permission checks
- `startup/` -- 11 modular initializer modules (one per concern)

## Startup Sequence (order matters)
1. telemetry (OpenTelemetry)
2. database schema check
3. LLM providers
4. graph service (Neo4j)
5. workflow engine
6. background tasks
7. Redis
8. DI container (global, db=None)
9. WebSocket manager
10. Docker services
11. channel manager (reload)

## Shutdown Sequence
channel manager -> Docker -> telemetry -> Neo4j (reverse of critical services)

## Exception Handling Pattern
- `ErrorResponse` format: `error_id` (UUID), `message`, `detail`, `retryable` flag
- Domain exceptions map to HTTP codes in `exception_handlers.py`
- `DomainException` -> 400, `NotFoundError` -> 404, `AuthError` -> 401/403
- Unhandled exceptions -> 500 with generated `error_id` for log correlation

## Middleware Stack
- CORS: configured via `settings.api_allowed_origins` (not hardcoded)
- Rate limiting: slowapi `limiter` instance
- Static files: served from `static/` directory at app level

## Startup Modules (startup/)
| Module | Responsibility |
|--------|---------------|
| `container.py` | Global DIContainer init (db=None) |
| `database.py` | Schema verification, session factory |
| `docker.py` | Docker service initialization |
| `graph.py` | Neo4j connection + index creation |
| `llm.py` | LLM provider registration |
| `redis.py` | Redis connection pool |
| `telemetry.py` | OpenTelemetry + Jaeger |
| `websocket.py` | WebSocket connection manager |
| `workflow.py` | Workflow engine setup |
| `channels.py` | Event channel registration |
| `channel_reload.py` | Hot-reload channel config |

## Gotchas
- `lifespan()` swallows startup errors with logging -- app starts even if Neo4j/Redis fail
- Global container at `request.app.state.container` has `db=None` -- see root AGENTS.md for session patterns
- Adding new startup step: create module in `startup/`, call from `lifespan()`
- Rate limiter state is in-memory (not Redis-backed) -- resets on restart
