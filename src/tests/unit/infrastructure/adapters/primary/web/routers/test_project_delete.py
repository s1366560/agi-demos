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
async def test_project_delete_purges_external_sandbox_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MagicMock()
    adapter.purge_project_resources = AsyncMock()
    from src.infrastructure.plugins.v2 import sandbox_projection

    projection = MagicMock(return_value=SimpleNamespace(adapter=adapter))
    monkeypatch.setattr(sandbox_projection, "current_sandbox_application_services_v2", projection)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    await projects._purge_project_sandbox_resources(
        request,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        project_id="project-1",
    )

    adapter.purge_project_resources.assert_awaited_once_with("tenant-1", "project-1")


@pytest.mark.unit
async def test_project_delete_returns_503_when_external_resource_purge_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MagicMock()
    adapter.purge_project_resources = AsyncMock(side_effect=RuntimeError("docker unavailable"))
    from src.infrastructure.plugins.v2 import sandbox_projection

    projection = MagicMock(return_value=SimpleNamespace(adapter=adapter))
    monkeypatch.setattr(sandbox_projection, "current_sandbox_application_services_v2", projection)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as exc_info:
        await projects._purge_project_sandbox_resources(
            request,  # type: ignore[arg-type]
            tenant_id="tenant-1",
            project_id="project-1",
        )

    assert exc_info.value.status_code == 503
    assert "docker unavailable" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_project_delete_uses_pinned_sandbox_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
    from src.infrastructure.plugins.v2 import sandbox_projection
    from src.infrastructure.plugins.v2.sandbox_runtime import (
        SANDBOX_APPLICATION_SERVICE_V2,
        SandboxApplicationResolverV2,
        SandboxRuntimeServiceV2,
    )

    adapter = SimpleNamespace(purge_project_resources=AsyncMock())
    resolver = SandboxApplicationResolverV2(
        runtime=SandboxRuntimeServiceV2(services=SimpleNamespace(adapter=adapter))
    )
    generation = MagicMock()
    generation.resolve.return_value = resolver
    monkeypatch.setattr(sandbox_projection, "current_generation_v2", lambda: generation)
    await projects._purge_project_sandbox_resources(
        SimpleNamespace(), tenant_id="tenant-1", project_id="project-1"
    )
    generation.resolve.assert_called_once_with(
        SANDBOX_APPLICATION_SERVICE_V2, ScopeV2(kind=ScopeKindV2.ROOT)
    )
    adapter.purge_project_resources.assert_awaited_once_with("tenant-1", "project-1")


@pytest.mark.unit
@pytest.mark.parametrize("authorized", [False, True])
async def test_project_delete_authorization_and_unavailable_runtime_never_commit(
    monkeypatch: pytest.MonkeyPatch, authorized: bool
) -> None:
    from src.infrastructure.plugins.v2 import sandbox_projection
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    db = SimpleNamespace(
        execute=AsyncMock(return_value=_Result(["tenant-1"] if authorized else [])),
        commit=AsyncMock(),
    )
    lock = AsyncMock(return_value=True)
    dependents = AsyncMock()
    projection = MagicMock(side_effect=RuntimeV2Error("sandbox_runtime_unavailable", "unavailable"))
    monkeypatch.setattr(projects, "_lock_project_delete_scope", lock)
    monkeypatch.setattr(projects, "_delete_project_dependents", dependents)
    monkeypatch.setattr(sandbox_projection, "current_sandbox_application_services_v2", projection)
    with pytest.raises(HTTPException) as failure:
        await projects.delete_project(
            "project-1",
            SimpleNamespace(),
            current_user=SimpleNamespace(id="owner-1"),
            project_tenant=SimpleNamespace(db=db),
        )
    assert failure.value.status_code == (503 if authorized else 403)
    assert db.execute.await_count == 1
    db.commit.assert_not_awaited()
    dependents.assert_not_awaited()
    if authorized:
        lock.assert_awaited_once_with(db, "project-1")
        projection.assert_called_once_with()
    else:
        lock.assert_not_awaited()
        projection.assert_not_called()
