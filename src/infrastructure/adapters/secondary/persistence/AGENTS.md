# persistence/ -- SQLAlchemy Repository Layer

## Purpose
32 repository implementations + unified ORM model definitions. All PostgreSQL persistence.

## Key Files
- `models.py` (1584 lines) -- ALL SQLAlchemy ORM models (single file)
- `database.py` -- `async_session_factory`, `get_db` dependency
- `sql_*.py` (32 files) -- one repository per domain entity
- `../common/base_repository.py` (585 lines) -- generic CRUD base class

## BaseRepository[T, M] Pattern
```python
class SqlMemoryRepository(BaseRepository[Memory, MemoryModel], MemoryRepository):
    _model_class = MemoryModel          # REQUIRED
    def _to_domain(self, db) -> Memory:  # REQUIRED
    def _to_db(self, entity) -> Model:   # Optional (base has default)
    def _update_fields(self) -> list:    # Optional (controls which fields update)
    def _eager_load_options(self) -> list: # Optional (joinedload, selectinload)
```

## Transaction Rules
- Repositories call `flush()` internally -- NEVER `commit()`
- Caller (endpoint or service) is responsible for `await db.commit()`
- `@transactional` decorator exists but is rarely used
- `handle_db_errors` decorator: `IntegrityError` -> `DuplicateEntityError`, `DBAPIError` -> `ConnectionError`

## Field Name Mapping Gotcha
Domain and DB field names sometimes differ:
- `Memory.metadata` <-> `MemoryModel.meta` (reserved word avoidance)
- Always check both `_to_domain()` and `_to_db()` when debugging field issues

## models.py Structure
- Single `Base = declarative_base()` for all models
- Models use `__tablename__` convention: snake_case plural (e.g., `memories`, `users`)
- Relationships declared with `relationship()` + `back_populates`
- Indexes and constraints defined in model classes
- `created_at` / `updated_at` columns use `server_default=func.now()`

## Adding a New Repository
1. Add ORM model to `models.py` with proper tablename, columns, relationships
2. Create `sql_new_entity_repository.py`
3. Extend `BaseRepository[NewEntity, NewEntityModel]` and domain port interface
4. Implement `_model_class`, `_to_domain()`, `_to_db()` at minimum
5. Register in `di_container.py`
6. Generate Alembic migration: `PYTHONPATH=. uv run alembic revision --autogenerate -m "add new_entity"`

## Gotchas
- `models.py` is 1584 lines -- be careful with merge conflicts; add models at bottom
- `_eager_load_options()` default is empty -- N+1 queries if relationships accessed without it
- `find_by_id` returns `Optional[T]` -- always handle None case
- Soft deletes: some models have `deleted_at` column, some do hard delete -- check per entity
- Bulk operations: use `_session.execute(insert(...))` for performance, not `save()` in loop
