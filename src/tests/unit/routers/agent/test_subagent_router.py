"""Tests for SubAgent control route hardening."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.agent import subagent_router
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    AgentSubAgentControlUnavailableV2,
)


class FailingSubAgentControl:
    async def request_cancel(self, **_kwargs: object) -> None:
        raise RuntimeError("internal redis cancel secret")


class UnavailableSubAgentControl:
    async def request_cancel(self, **_kwargs: object) -> None:
        raise AgentSubAgentControlUnavailableV2("internal unavailable detail")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_subagent_execution_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await subagent_router.cancel_subagent_execution(
            execution_id="exec-secret",
            request=SimpleNamespace(),
            body=subagent_router.CancelSubAgentRequest(reason="stop"),
            current_user=SimpleNamespace(id="user-1"),
            subagent_control=SimpleNamespace(service=FailingSubAgentControl()),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to cancel SubAgent execution"
    assert "internal" not in exc_info.value.detail
    assert "exec-secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_subagent_execution_reports_generation_redis_unavailable() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await subagent_router.cancel_subagent_execution(
            execution_id="exec-a",
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1"),
            subagent_control=SimpleNamespace(service=UnavailableSubAgentControl()),
        )

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == "Redis is not available. Cannot signal cancellation."
