"""Project deletion concurrency and receipt-preservation tests."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from src.infrastructure.adapters.primary.web.routers import projects


class _Result:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def scalar_one_or_none(self) -> str | None:
        return self.values[0] if self.values else None

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[str]:
        return self.values


class _CaptureSession:
    def __init__(self, results: list[list[str]]) -> None:
        self.results = iter(results)
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(next(self.results, []))


def _postgres_sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.unit
async def test_project_delete_scope_uses_shared_stable_lock_order() -> None:
    session = _CaptureSession(
        [
            ["project-1"],
            ["membership-2", "membership-1"],
        ]
    )

    assert await projects._lock_project_delete_scope(session, "project-1") is True  # type: ignore[arg-type]

    statements = session.statements
    assert len(statements) == 2
    rendered = [_postgres_sql(statement) for statement in statements]
    assert "FROM projects" in rendered[0]
    assert "FROM user_projects" in rendered[1]
    assert "ORDER BY user_projects.id" in rendered[1]
    assert all("FOR UPDATE" in sql for sql in rendered)


@pytest.mark.unit
async def test_project_dependent_delete_preserves_receipts_until_root_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Connection:
        async def run_sync(self, callback: Any) -> set[str]:
            return callback(object())

    class _DeleteSession:
        async def connection(self) -> _Connection:
            return _Connection()

        async def execute(self, _statement: Any) -> _Result:
            return _Result([])

    class _Inspector:
        @staticmethod
        def get_table_names() -> list[str]:
            return [
                "messages",
                "conversations",
                projects.TASK_SESSION_RECEIPT_TABLE,
            ]

    calls: list[dict[str, Any]] = []

    async def capture_delete_references(_db: Any, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(projects, "inspect", lambda _connection: _Inspector())
    monkeypatch.setattr(projects, "_delete_rows_referencing", capture_delete_references)

    await projects._delete_project_dependents(_DeleteSession(), "project-1")  # type: ignore[arg-type]

    assert [call["target_table_name"] for call in calls] == [
        "messages",
        "conversations",
        "projects",
    ]
    assert projects.TASK_SESSION_RECEIPT_TABLE in calls[0]["skip_tables"]
    assert projects.TASK_SESSION_RECEIPT_TABLE in calls[1]["skip_tables"]
    assert projects.TASK_SESSION_RECEIPT_TABLE not in calls[2]["skip_tables"]


@pytest.mark.unit
async def test_project_delete_purges_external_sandbox_resources() -> None:
    adapter = MagicMock()
    adapter.purge_project_resources = AsyncMock()
    container = MagicMock()
    container.sandbox_adapter.return_value = adapter
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))

    await projects._purge_project_sandbox_resources(
        request,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        project_id="project-1",
    )

    adapter.purge_project_resources.assert_awaited_once_with("tenant-1", "project-1")


@pytest.mark.unit
async def test_project_delete_returns_503_when_external_resource_purge_fails() -> None:
    adapter = MagicMock()
    adapter.purge_project_resources = AsyncMock(side_effect=RuntimeError("docker unavailable"))
    container = MagicMock()
    container.sandbox_adapter.return_value = adapter
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))

    with pytest.raises(HTTPException) as exc_info:
        await projects._purge_project_sandbox_resources(
            request,  # type: ignore[arg-type]
            tenant_id="tenant-1",
            project_id="project-1",
        )

    assert exc_info.value.status_code == 503
    assert "docker unavailable" not in str(exc_info.value.detail)
