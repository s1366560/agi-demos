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
