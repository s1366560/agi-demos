"""Project deletion concurrency and receipt-preservation tests."""

from typing import Any

import pytest
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
            ["workspace-b", "workspace-a", "workspace-a"],
            ["member-2", "member-1"],
        ]
    )

    assert await projects._lock_project_delete_scope(session, "project-1") is True  # type: ignore[arg-type]

    statements = session.statements
    assert len(statements) == 4
    rendered = [_postgres_sql(statement) for statement in statements]
    assert "FROM projects" in rendered[0]
    assert "FROM user_projects" in rendered[1]
    assert "ORDER BY user_projects.id" in rendered[1]
    assert "FROM workspaces" in rendered[2]
    assert "ORDER BY workspaces.id" in rendered[2]
    assert "FROM workspace_members" in rendered[3]
    assert "ORDER BY workspace_members.workspace_id, workspace_members.id" in rendered[3]
    assert all("FOR UPDATE" in sql for sql in rendered)

    workspace_member_params = statements[3].compile(dialect=postgresql.dialect()).params
    assert workspace_member_params["workspace_id_1"] == ["workspace-a", "workspace-b"]


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
                "workspaces",
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
        "workspaces",
        "projects",
    ]
    assert projects.TASK_SESSION_RECEIPT_TABLE in calls[0]["skip_tables"]
    assert projects.TASK_SESSION_RECEIPT_TABLE in calls[1]["skip_tables"]
    assert projects.TASK_SESSION_RECEIPT_TABLE not in calls[2]["skip_tables"]
    assert projects.TASK_SESSION_RECEIPT_TABLE not in calls[3]["skip_tables"]
