"""Tests for plan-mode route hardening."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent.plans import (
    SwitchModeRequest,
    get_mode,
    get_tasks,
    switch_mode,
)


class FailingDb:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("internal db secret")

    async def commit(self) -> None:
        return None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_switch_mode_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await switch_mode(
            request_body=SwitchModeRequest(conversation_id="conversation-1", mode="plan"),
            current_user=SimpleNamespace(id="user-1"),
            db=FailingDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to switch mode"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_mode_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_mode(
            conversation_id="conversation-1",
            current_user=SimpleNamespace(id="user-1"),
            db=FailingDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get mode"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tasks_sanitizes_internal_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingTaskRepository:
        def __init__(self, db: Any) -> None:
            self.db = db

        find_by_conversation = AsyncMock(side_effect=RuntimeError("internal task secret"))

    import src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository as task_repo

    monkeypatch.setattr(task_repo, "SqlAgentTaskRepository", FailingTaskRepository)

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-1",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get tasks"
    assert "internal" not in exc_info.value.detail
