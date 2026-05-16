"""Tests for subagent route hardening."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers import subagents as subagents_router


class EmptySubAgentRepository:
    async def get_by_name(self, _tenant_id: str, _name: str) -> None:
        return None


class EmptyContainer:
    def subagent_repository(self) -> EmptySubAgentRepository:
        return EmptySubAgentRepository()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_subagent_value_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subagents_router,
        "get_container_with_db",
        lambda _request, _db: EmptyContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await subagents_router.create_subagent(
            request=SimpleNamespace(),
            data=subagents_router.SubAgentCreate(
                name="agent-1",
                display_name="Agent 1",
                system_prompt="You are helpful.",
                trigger_description="Use for tests.",
                model="internal-model-secret",
            ),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid subagent request"
    assert "internal-model-secret" not in exc_info.value.detail
