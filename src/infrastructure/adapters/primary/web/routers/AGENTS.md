# routers/ -- API Endpoint Definitions

FastAPI router layer for the primary web adapter.

Last checked against code: 2026-05-18.

## Current Shape

- 90+ router files under this directory and subdirectories.
- Major subdirectories: `agent/`, `mcp/`, `sandbox/`.
- Routers are registered in `src/infrastructure/adapters/primary/web/main.py`.
- Current live agent chat is WebSocket-based through `/api/v1/agent/ws`; there is no
  registered `/api/v1/agent/chat` route in the current router set.

## Major Areas

| Area | Representative files |
|---|---|
| Auth/tenant/project | `auth.py`, `tenants.py`, `projects.py`, `invitations.py` |
| Agent | `agent/__init__.py`, `agent/conversations.py`, `agent/messages.py`, `agent/events.py`, `agent/hitl.py`, `agent/tools.py`, `agent/trace_router.py` |
| WebSocket | `../websocket/router.py`, `../websocket/handlers/*` |
| Memory/graph/search | `memories.py`, `episodes.py`, `graph.py`, `schema.py`, `enhanced_search.py`, `recall.py`, `reflection.py` |
| Workspace | `workspaces.py`, `workspace_plans.py`, `workspace_tasks.py`, `workspace_autonomy.py`, `workspace_chat.py`, `blackboard.py`, `topology.py` |
| Sandbox/MCP/terminal | `sandbox/*`, `project_sandbox.py`, `mcp/*`, `terminal.py`, `tunnel.py` |
| Product/admin | `skills.py`, `skills_curated.py`, `subagents.py`, `channels.py`, `instances.py`, `deploy.py`, `genes.py`, `audit.py`, `trust.py`, `observability.py`, `admin_dlq.py` |

## Standard Endpoint Pattern

```python
@router.get("/items")
async def list_items(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    container = get_container_with_db(request, db)
    service = container.some_service()
    result = await service.list()
    await db.commit()
    return result
```

Use the pattern in the neighboring router first; this layer still mixes direct repository
construction, scoped DI containers, and focused SQLAlchemy queries.

## Auth And DB Rules

- Use `Depends(get_current_user)` and/or tenant helpers for authenticated endpoints.
- Scope reads and writes by tenant/project/conversation where applicable.
- `Depends(get_db)` sessions are not auto-committed; endpoints that mutate must commit.
- The global app container has singleton services only. Use `get_container_with_db` or direct
  repository construction for DB-backed services.

## Agent Router Specifics

`agent/__init__.py` aggregates:

- commands,
- conversations,
- participants,
- messages,
- tools,
- patterns,
- config,
- HITL,
- events,
- templates,
- plan mode,
- subagent cancellation,
- bindings,
- definitions,
- trace,
- agent graph routes.

HITL response delivery persists to PostgreSQL and publishes to Redis streams for Ray actor
resume. Workflow execution is handled by the current asyncio/Ray runtime, not Temporal.

## Adding A Router

1. Create a focused router file with `router = APIRouter(prefix="/api/v1/...", tags=[...])`.
2. Register it in `main.py`.
3. Keep schemas local only if they are route-specific; shared schemas belong in application
   schema modules.
4. Add tests for auth, tenant/project scoping, validation, and commit behavior.
5. Update `docs/api-reference.md` when the route family is public.

## Gotchas

- Avoid expanding already-large routers such as `projects.py`, `memories.py`,
  `workspace_plans.py`, and `skills.py` unless the surrounding pattern makes it necessary.
- Register more-specific routes before generic path-parameter routes.
- Keep frontend path conventions in mind: web services are relative to `/api/v1`.
