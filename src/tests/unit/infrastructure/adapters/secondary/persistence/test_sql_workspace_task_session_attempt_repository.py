"""Tests for SQL workspace task session attempt persistence helpers."""

from __future__ import annotations

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
