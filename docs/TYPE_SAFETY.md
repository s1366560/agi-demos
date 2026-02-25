# Type Safety Guidelines

This document defines the type safety standards for the MemStack codebase. All Python code
in `src/`, `sdk/`, and `scripts/` must pass these checks before commit.

## Overview

Three tools enforce type safety at different levels:

| Tool | Mode | Scope | Purpose |
|------|------|-------|---------|
| **Pyright** | `strict` | Pre-commit hook + CI | Primary type checker. 40+ explicit error rules. Runs on staged files at commit time. |
| **Mypy** | `strict` | CI (`make lint-backend`) | Secondary type checker. Catches different classes of errors than pyright. |
| **Ruff** | ANN rules | Pre-commit hook + CI | Enforces presence of type annotations on function signatures. |

Python version target: **3.12** (all three tools).

---

## Pyright Configuration

Config file: `pyrightconfig.json`

### Scope

**Included directories:** `src`, `sdk`, `scripts`

**Excluded directories:**
- `src/tests` -- test files are exempt
- `src/alembic` -- migration files are exempt
- `src/memstack_agent` -- legacy code, migrating progressively
- `web`, `notebooks`, `design-prototype`, `.venv`, `node_modules`, `__pycache__`

### Strict Mode Settings

```
typeCheckingMode: "strict"
analyzeUnannotatedFunctions: true
strictListInference: true
strictDictionaryInference: true
strictSetInference: true
strictParameterNoneValue: true
deprecateTypingAliases: true
disableBytesTypePromotions: true
```

### Explicit Error Rules

Each rule below is set to `"error"` in pyrightconfig.json:

| Rule | What It Catches |
|------|-----------------|
| `reportMissingTypeStubs` | Import of a library with no type stubs available |
| `reportImportCycles` | Circular import dependencies between modules |
| `reportPrivateUsage` | Access to private members (prefixed with `_`) from outside the class |
| `reportTypeCommentUsage` | Legacy `# type:` comments instead of inline annotations |
| `reportUntypedFunctionDecorator` | Decorators that strip type information |
| `reportUntypedClassDecorator` | Class decorators without proper typing |
| `reportUntypedBaseClass` | Inheriting from an untyped base class |
| `reportUntypedNamedTuple` | NamedTuple without field type annotations |
| `reportConstantRedefinition` | Reassigning a variable declared as Final or constant |
| `reportDeprecated` | Use of deprecated APIs |
| `reportImplicitStringConcatenation` | Adjacent string literals without explicit `+` operator |
| `reportUnnecessaryIsInstance` | isinstance() check that is always true |
| `reportUnnecessaryCast` | cast() call that has no effect |
| `reportUnnecessaryComparison` | Comparison that is always true or false |
| `reportUnnecessaryContains` | `in` check that is always true or false |
| `reportCallInDefaultInitializer` | Function calls in default parameter values |
| `reportMissingSuperCall` | `__init__` that does not call `super().__init__()` |
| `reportUninitializedInstanceVariable` | Instance variable used before assignment |
| `reportUnknownParameterType` | Parameter with unknown/unresolvable type |
| `reportUnknownArgumentType` | Argument with unknown/unresolvable type |
| `reportUnknownLambdaType` | Lambda with unresolvable types |
| `reportUnknownVariableType` | Variable with unknown type |
| `reportUnknownMemberType` | Attribute access returning unknown type |
| `reportMissingParameterType` | Function parameter without type annotation |
| `reportMissingTypeArgument` | Generic used without type parameters (e.g., `list` instead of `list[str]`) |
| `reportInvalidTypeVarUse` | Incorrect TypeVar usage |
| `reportUnusedCallResult` | Function return value silently discarded |
| `reportUnusedExpression` | Expression with no side effect and unused result |
| `reportUnnecessaryTypeIgnoreComment` | `# type: ignore` that suppresses no actual error |
| `reportMatchNotExhaustive` | `match` statement missing cases |
| `reportImplicitOverride` | Method override without `@override` decorator |
| `reportPropertyTypeMismatch` | Property getter/setter type mismatch |

---

## Mypy Configuration

Config file: `pyproject.toml` section `[tool.mypy]`

### Strict Mode Flags

```
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_any_generics = true
disallow_subclassing_any = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_unreachable = true
strict_equality = true
```

### Excluded Directories

Same as pyright: `src/tests/`, `src/alembic/`, `src/memstack_agent/`

### Per-Module Overrides

**LiteLLM adapter** (`src.infrastructure.llm.litellm.*`):
- `ignore_errors = true` -- 25 remaining errors from untyped library internals

**Third-party libraries without stubs** (docker, yaml, boto3, lark_oapi, pgvector, psycopg2, networkx, jsonschema, grpc):
- `ignore_missing_imports = true`

**Internal optional modules** (`embedding_service`, `embedding_utils`):
- `ignore_missing_imports = true` -- may not exist in all environments

### Deferred Rules (Phase 2)

These are commented out in config, planned for incremental enablement:
- `disallow_untyped_calls` -- 2362 errors
- `disallow_incomplete_defs`
- `check_untyped_defs`

---

## Ruff ANN Rules

Config file: `pyproject.toml` section `[tool.ruff.lint]`

### Active Annotation Rules

| Rule | Enforces |
|------|----------|
| `ANN001` | Type annotation on function parameters |
| `ANN002` | Type annotation on `*args` |
| `ANN003` | Type annotation on `**kwargs` |
| `ANN201` | Return type annotation on public functions |
| `ANN202` | Return type annotation on private functions |
| `ANN401` | Disallows `Any` in function signatures |

### Per-File Exemptions

**Test files** (`src/tests/**`): All ANN rules relaxed (ANN001-003, ANN201-202).

**Alembic migrations** (`src/alembic/**`): All ANN rules relaxed.

**Specific files**: Many infrastructure files have `ANN401` exemptions for functions
that genuinely need `Any` (e.g., serialization adapters, LLM response handlers).
See `[tool.ruff.lint.per-file-ignores]` in pyproject.toml for the full list.

### TCH Rules (Type-Checking Imports)

`TCH` rules are suppressed globally for `src/**` via per-file-ignores.
These optimize imports behind `if TYPE_CHECKING:` blocks. Planned for Wave 2 enablement.

---

## Common Type Annotation Patterns

### Domain Model (Dataclass)

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass(kw_only=True)
class Entity:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def update_name(self, new_name: str) -> None:
        if not new_name:
            raise ValueError("Name cannot be empty")
        self.name = new_name
```

Key rules:
- Every field has an explicit type annotation.
- Use `Optional[X]` (or `X | None`) for nullable fields.
- Factory defaults use `field(default_factory=...)`.
- Methods annotate all parameters and return types.

### FastAPI Endpoint

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.database import get_db

router = APIRouter()


@router.get("/items/{item_id}")
async def get_item(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db),
) -> ItemResponse:
    container = get_container_with_db(request, db)
    service = container.item_service()
    item = await service.get_by_id(item_id)
    return ItemResponse.from_domain(item)
```

Key rules:
- All parameters have type annotations, including `Depends()` injections.
- Return type is always annotated (the response DTO, not `dict`).
- `Request` and `AsyncSession` are typed explicitly.

### Repository Method

```python
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlEntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(self, entity_id: str) -> Optional[Entity]:
        query = select(EntityModel).where(EntityModel.id == entity_id)
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    def _to_domain(self, model: EntityModel) -> Entity:
        return Entity(id=model.id, name=model.name)
```

Key rules:
- Constructor annotates `session` parameter and returns `-> None`.
- `Optional[X]` for methods that may return `None`.
- Private methods (`_to_domain`) also need return type annotations (ANN202).

### Service Constructor (Dependency Injection)

```python
import logging

from src.domain.ports.repositories import EntityRepository

logger = logging.getLogger(__name__)


class EntityService:
    def __init__(self, entity_repo: EntityRepository) -> None:
        self._entity_repo = entity_repo

    async def create(self, name: str) -> Entity:
        entity = Entity(name=name)
        await self._entity_repo.save(entity)
        logger.info("Created entity %s", entity.id)
        return entity
```

Key rules:
- Constructor parameters use the **port interface** type, not the concrete implementation.
- All `async` methods have explicit return types.

### Generic Containers

```python
# Use built-in generic syntax (Python 3.12+)
items: list[str] = []
mapping: dict[str, int] = {}
result: tuple[str, int] = ("key", 42)
optional_name: str | None = None

# For complex types, use typing module
from typing import Sequence, Mapping
from collections.abc import Callable, Awaitable

def process(
    items: Sequence[str],
    callback: Callable[[str], Awaitable[None]],
) -> list[str]:
    ...
```

Key rules:
- Prefer `list[X]` over `List[X]`, `dict[K, V]` over `Dict[K, V]` (Python 3.12+).
- Prefer `X | None` over `Optional[X]` in new code.
- Use `Sequence` / `Mapping` for read-only parameters (covariant).
- Use `list` / `dict` for mutable return types.

---

## Handling `type: ignore` Comments

### When Acceptable

- **Third-party library issues**: Library has incorrect or missing stubs and no fix is available.
- **SQLAlchemy dynamic attributes**: ORM-generated attributes that type checkers cannot resolve.
- **Intentional override of checker behavior**: When you are certain the code is correct but
  the checker cannot prove it (e.g., dynamic dispatch patterns).

### When NOT Acceptable

- Suppressing errors from your own code to "make it pass."
- Hiding actual type mismatches or missing annotations.
- Using `as any` or `# type: ignore` instead of writing proper types.

### Required Format

Always include the specific error code and a reason:

```python
# Acceptable
value = obj.dynamic_attr  # type: ignore[attr-defined]  # SQLAlchemy dynamic column

# NOT acceptable
value = obj.dynamic_attr  # type: ignore
```

Pyright enforces `reportUnnecessaryTypeIgnoreComment` -- stale ignore comments are errors.

---

## Pre-commit Workflow

### What Runs on Commit

The `.githooks/pre-commit` hook runs automatically on `git commit`:

1. **Ruff check** on all staged Python files (fast lint pass).
2. **Pyright** on staged Python files within scope:
   - Included: `src/`, `sdk/`, `scripts/`
   - Excluded: `src/tests/`, `src/alembic/`, `src/memstack_agent/`
3. **ESLint** on staged TypeScript/JavaScript files in `web/`.

### Setup

```bash
make hooks-install    # Sets git config core.hooksPath to .githooks
```

### Manual Execution

```bash
# Run pyright on entire project
make type-check-pyright

# Run mypy on entire project
make type-check-mypy

# Run all linters (ruff + mypy + pyright)
make lint-backend

# Run pyright on a single file
uv run pyright src/path/to/file.py

# Run mypy on a single file
uv run mypy src/path/to/file.py --ignore-missing-imports
```

### Bypassing (Emergency Only)

```bash
git commit --no-verify -m "emergency: reason for bypass"
```

This skips all pre-commit hooks. Use only for genuine emergencies and follow up with a fix.

---

## Tech Debt Baseline

As of the initial type safety enforcement rollout:

- **402** `type: ignore` comments across **132** files
- Most are in infrastructure adapters dealing with third-party libraries
- LiteLLM module has `ignore_errors = true` in mypy (25 remaining errors)
- Many infrastructure files have `ANN401` exemptions in ruff

This debt is being reduced incrementally. Do not add new `type: ignore` without
a specific error code and documented reason.

---

## Troubleshooting

### "reportMissingTypeStubs" (pyright)

```
error: Import "some_library" could not be resolved from source
```

**Fix**: Add a `py.typed` marker or install stubs. If no stubs exist, add the module
to mypy's `ignore_missing_imports` override and use inline `# pyright: ignore` for
the specific import.

### "reportUnknownParameterType" (pyright)

```
error: Type of parameter "x" is unknown
```

**Fix**: Add explicit type annotation to the parameter.

### "ANN401 - Dynamically typed expressions (typing.Any) are disallowed"

```
ANN401 Dynamically typed expressions (typing.Any) are disallowed in `param`
```

**Fix**: Replace `Any` with a concrete type, `object`, a Protocol, or a TypeVar.
If the function genuinely needs `Any` (e.g., JSON serialization), add the file
to `per-file-ignores` for `ANN401` in pyproject.toml.

### "Argument of type X is not assignable to parameter of type Y"

Common with SQLAlchemy models where `Column` types differ from Python types.

**Fix**: Ensure model fields use the correct Python type annotation. For ORM
attributes, use the mapped type (e.g., `str` not `Column[String]`).

### "reportImplicitStringConcatenation"

```
error: Implicit string concatenation not allowed
```

**Fix**: Use explicit `+` operator or parenthesized multi-line strings:

```python
# Wrong
message = "line one"
    "line two"

# Correct
message = (
    "line one"
    " line two"
)
```

### mypy vs pyright Disagreements

When one checker passes but the other fails on the same code:
1. Fix for the stricter checker (usually pyright in strict mode).
2. If they have genuinely conflicting requirements, prefer pyright and add
   a mypy-specific override in `pyproject.toml` if necessary.
3. Never suppress both with a blanket `# type: ignore`.
