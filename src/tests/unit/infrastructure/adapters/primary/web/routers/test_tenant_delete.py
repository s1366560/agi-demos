"""Tenant deletion lock-order tests."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call, patch

import pytest
from sqlalchemy.dialects import postgresql

from src.infrastructure.adapters.primary.web.routers import tenants


class _Result:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def scalar_one_or_none(self) -> Any | None:
        return self.values[0] if self.values else None

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return self.values


class _CaptureSession:
    def __init__(self, results: list[list[Any]]) -> None:
        self.results = iter(results)
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(next(self.results, []))


def _postgres_sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.unit
async def test_tenant_delete_scope_locks_parent_before_stable_project_tree() -> None:
    tenant = object()
    session = _CaptureSession(
        [
            [tenant],
            ["project-b", "project-a"],
            ["project-a", "project-b"],
            ["membership-2", "membership-1"],
        ]
    )

    locked_tenant, project_ids = await tenants._lock_tenant_delete_scope(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        owner_user_id="owner-1",
    )

    assert locked_tenant is tenant
    assert project_ids == ["project-a", "project-b"]
    rendered = [_postgres_sql(statement) for statement in session.statements]
    lock_statements = [sql for sql in rendered if "FOR UPDATE" in sql]
    # Workspaces are owned by Avernet Core; the platform delete scope locks
    # only tenants, projects, and user_projects.
    assert len(lock_statements) == 3
    assert "FROM tenants" in lock_statements[0]
    assert "FROM projects" in lock_statements[1]
    assert "ORDER BY projects.id" in lock_statements[1]
    assert "FROM user_projects" in lock_statements[2]
    assert "ORDER BY projects.id" in rendered[1]


@pytest.mark.unit
async def test_tenant_delete_purges_every_project_before_database_deletion() -> None:
    tenant = object()
    request = SimpleNamespace()
    user = SimpleNamespace(id="owner-1")
    db = SimpleNamespace(execute=AsyncMock(), delete=AsyncMock(), commit=AsyncMock())

    with (
        patch.object(
            tenants,
            "_lock_tenant_delete_scope",
            new=AsyncMock(return_value=(tenant, ["project-a", "project-b"])),
        ),
        patch.object(
            tenants,
            "_purge_project_sandbox_resources",
            new=AsyncMock(),
        ) as purge,
        patch.object(tenants, "_delete_project_dependents", new=AsyncMock()),
    ):
        await tenants.delete_tenant(
            "tenant-1",
            request,  # type: ignore[arg-type]
            current_user=user,  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert purge.await_args_list == [
        call(request, tenant_id="tenant-1", project_id="project-a"),
        call(request, tenant_id="tenant-1", project_id="project-b"),
    ]
    db.delete.assert_awaited_once_with(tenant)
    db.commit.assert_awaited_once_with()


@pytest.mark.unit
async def test_tenant_delete_does_not_mutate_database_when_resource_purge_fails() -> None:
    tenant = object()
    request = SimpleNamespace()
    user = SimpleNamespace(id="owner-1")
    db = SimpleNamespace(execute=AsyncMock(), delete=AsyncMock(), commit=AsyncMock())

    with (
        patch.object(
            tenants,
            "_lock_tenant_delete_scope",
            new=AsyncMock(return_value=(tenant, ["project-a"])),
        ),
        patch.object(
            tenants,
            "_purge_project_sandbox_resources",
            new=AsyncMock(side_effect=RuntimeError("docker unavailable")),
        ),
        patch.object(
            tenants,
            "_delete_project_dependents",
            new=AsyncMock(),
        ) as delete_dependents,
        pytest.raises(RuntimeError, match="docker unavailable"),
    ):
        await tenants.delete_tenant(
            "tenant-1",
            request,  # type: ignore[arg-type]
            current_user=user,  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    delete_dependents.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()
