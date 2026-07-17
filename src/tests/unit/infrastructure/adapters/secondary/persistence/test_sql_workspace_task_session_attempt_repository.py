"""Tests for SQL workspace task session attempt persistence helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_session_attempt_repository import (
    SqlWorkspaceTaskSessionAttemptRepository,
)


@pytest.mark.unit
class TestSqlWorkspaceTaskSessionAttemptRepository:
    @pytest.mark.asyncio
    async def test_lock_attempt_creation_uses_transaction_advisory_lock(self) -> None:
        class _Session:
            statement: Any = None
            params: dict[str, Any] | None = None

            async def execute(self, statement: Any, params: dict[str, Any]) -> None:
                self.statement = statement
                self.params = params

        session = _Session()
        repo = SqlWorkspaceTaskSessionAttemptRepository(cast(AsyncSession, session))

        await repo.lock_attempt_creation("task-123")

        assert "pg_advisory_xact_lock" in str(session.statement)
        assert "hashtextextended" in str(session.statement)
        assert session.params == {"workspace_task_id": "task-123"}

    @pytest.mark.asyncio
    async def test_stale_lookup_uses_conversation_event_activity(self) -> None:
        class _Result:
            class _Scalars:
                @staticmethod
                def all() -> list[Any]:
                    return []

            @staticmethod
            def scalars() -> _Scalars:
                return _Result._Scalars()

        class _Session:
            statement: Any = None

            async def execute(self, statement: Any) -> _Result:
                self.statement = statement
                return _Result()

        session = _Session()
        repo = SqlWorkspaceTaskSessionAttemptRepository(cast(AsyncSession, session))

        rows = await repo.find_stale_non_terminal(
            older_than=datetime.now(UTC) - timedelta(minutes=3)
        )

        assert rows == []
        sql = str(session.statement)
        assert "agent_execution_events" in sql
        assert "max(agent_execution_events.created_at)" in sql
        assert "CASE" in sql
        assert "workspace_task_session_attempts.created_at ASC" in sql
        assert "workspace_task_session_attempts.id ASC" in sql


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_by_workspace_task_ids_returns_latest_per_task_in_one_query(
    db_session: AsyncSession,
) -> None:
    from src.infrastructure.adapters.secondary.persistence.models import (
        Project,
        Tenant,
        User,
        WorkspaceModel,
        WorkspaceTaskModel,
        WorkspaceTaskSessionAttemptModel,
    )

    db_session.add_all(
        [
            User(
                id="batch-user-1",
                email="batch-user-1@example.com",
                full_name="Batch User",
                hashed_password="hash",
                is_active=True,
            ),
            Tenant(
                id="batch-tenant-1",
                name="Batch Tenant",
                slug="batch-tenant",
                description="",
                owner_id="batch-user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            Project(
                id="batch-project-1",
                tenant_id="batch-tenant-1",
                name="Batch Project",
                description="",
                owner_id="batch-user-1",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id="batch-workspace-1",
                tenant_id="batch-tenant-1",
                project_id="batch-project-1",
                name="Batch Workspace",
                description="",
                created_by="batch-user-1",
            ),
        ]
    )
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="batch-task-1",
                workspace_id="batch-workspace-1",
                title="Task 1",
                created_by="batch-user-1",
            ),
            WorkspaceTaskModel(
                id="batch-task-2",
                workspace_id="batch-workspace-1",
                title="Task 2",
                created_by="batch-user-1",
            ),
        ]
    )

    def _attempt(task_id: str, number: int) -> WorkspaceTaskSessionAttemptModel:
        return WorkspaceTaskSessionAttemptModel(
            id=f"batch-attempt-{task_id}-{number}",
            workspace_task_id=task_id,
            root_goal_task_id=task_id,
            workspace_id="batch-workspace-1",
            attempt_number=number,
            status="accepted",
        )

    db_session.add_all(
        [
            _attempt("batch-task-1", 1),
            _attempt("batch-task-1", 2),
            _attempt("batch-task-1", 3),
            _attempt("batch-task-1", 4),
            _attempt("batch-task-2", 1),
        ]
    )
    await db_session.flush()

    repo = SqlWorkspaceTaskSessionAttemptRepository(db_session)
    attempts_by_task = await repo.find_by_workspace_task_ids(
        ["batch-task-1", "batch-task-2", "batch-task-missing"],
        limit_per_task=2,
    )

    # Per-task limit enforced in SQL, latest attempts first.
    assert [a.attempt_number for a in attempts_by_task["batch-task-1"]] == [4, 3]
    assert [a.attempt_number for a in attempts_by_task["batch-task-2"]] == [1]
    assert attempts_by_task["batch-task-missing"] == []
