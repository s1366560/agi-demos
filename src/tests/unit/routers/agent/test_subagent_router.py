"""Tests for SubAgent control route hardening."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.agent import subagent_router


class FailingRedis:
    async def set(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("internal redis cancel secret")


class FakeContainer:
    def redis(self) -> FailingRedis:
        return FailingRedis()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_subagent_execution_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subagent_router,
        "get_container_with_db",
        lambda _request, _db: FakeContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await subagent_router.cancel_subagent_execution(
            execution_id="exec-secret",
            request=SimpleNamespace(),
            body=subagent_router.CancelSubAgentRequest(reason="stop"),
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to cancel SubAgent execution"
    assert "internal" not in exc_info.value.detail
    assert "exec-secret" not in exc_info.value.detail
