"""Tenant deletion lock-order tests."""

from typing import Any

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
            ["workspace-b", "workspace-a"],
            ["member-2", "member-1"],
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
    assert len(lock_statements) == 5
    assert "FROM tenants" in lock_statements[0]
    assert "FROM projects" in lock_statements[1]
    assert "ORDER BY projects.id" in lock_statements[1]
    assert "FROM user_projects" in lock_statements[2]
    assert "FROM workspaces" in lock_statements[3]
    assert "FROM workspace_members" in lock_statements[4]
    assert "ORDER BY projects.id" in rendered[1]
