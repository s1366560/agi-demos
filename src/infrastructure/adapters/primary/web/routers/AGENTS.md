# routers/ -- API Endpoint Definitions

## Purpose
31+ router modules plus `agent/`, `mcp/`, `sandbox/` subdirectories. All FastAPI endpoint definitions.

## Structure
- Top-level: `projects.py`, `memories.py`, `episodes.py`, `entities.py`, `tenants.py`, `users.py`, etc.
- `agent/` subdir: 14 files -- chat, conversations, plans, skills, sub_agents, tools, work_plans, hitl, artifacts
- `mcp/` subdir: MCP server/tool management endpoints
- `sandbox/` subdir: sandbox lifecycle endpoints

## Standard Endpoint Pattern
```python
@router.get("/items")
async def list_items(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Build services with per-request session
    container = get_container_with_db(request, db)
    service = container.some_service()
    result = await service.list()
    await db.commit()  # Caller commits
    return result
```

## Auth Patterns
- `current_user: User = Depends(get_current_user)` -- JWT token validation
- Role checks: manual SQLAlchemy queries against `UserProject` / `UserTenant` join tables
- No decorator-based RBAC -- inline permission checks in each endpoint
- Tenant isolation: most queries scoped by `current_user.tenant_id`

## Known Inconsistencies
- `projects.py` (884 lines) and `memories.py` (974 lines) use **raw SQLAlchemy queries** instead of repository pattern
- Agent routers use `get_container_with_db(request, db)` from `agent/utils.py`
- Some routers build repositories directly: `SqlXxxRepository(db)`
- No uniform pattern enforced -- check existing file in same subdir before adding

## Agent Router Specifics (agent/ subdir)
- `utils.py`: `get_container_with_db(request, db)` -- clones global container with real DB session
- `chat_handler.py`: SSE streaming via Redis Stream bridge to WebSocket
- `conversations.py`: conversation CRUD + message history
- `plans.py`, `work_plans.py`: plan lifecycle endpoints

## Memory Router Specifics
- `POST /memories` triggers Temporal workflow for graph processing (async)
- `PUT /memories/{id}` uses optimistic locking via `version` field
- `POST /memories/{id}/share` copies memory across projects
- `POST /memories/reprocess` re-extracts entities from existing memories

## Adding a New Router
1. Create `new_feature.py` in this directory
2. Define `router = APIRouter(prefix="/api/v1/new-feature", tags=["new-feature"])`
3. Register in `main.py` via `app.include_router(router)`
4. Use `Depends(get_db)` for DB access, `Depends(get_current_user)` for auth
5. Caller (endpoint) is responsible for `await db.commit()`

## Gotchas
- Oversized routers (projects.py, memories.py) -- do NOT add more raw SQL; use repositories
- `get_container_with_db` preserves graph_service and redis_client from global container
- No request validation middleware -- validation is per-endpoint via Pydantic schemas
- Pagination: most list endpoints accept `skip`/`limit` params, not cursor-based
