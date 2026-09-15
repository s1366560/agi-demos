"""Tests for SubAgent control route hardening."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.agent import subagent_router
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
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
            body=subagent_router.CancelSubAgentRequest(
                reason="stop", conversation_id="conversation"
            ),
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
            body=subagent_router.CancelSubAgentRequest(conversation_id="conversation"),
            current_user=SimpleNamespace(id="user-1"),
            subagent_control=SimpleNamespace(service=UnavailableSubAgentControl()),
        )

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == "Redis is not available. Cannot signal cancellation."


@pytest.fixture(autouse=True)
def registry_boundary(monkeypatch):
    registry = SubAgentRunRegistry(sync_across_processes=False, recover_inflight_on_boot=False)
    for run_id in ("exec-a", "exec-secret"):
        registry.create_run("conversation", "worker", "task", run_id=run_id)
        registry.mark_running("conversation", run_id)
    monkeypatch.setattr(subagent_router, "current_subagent_run_registry_v2", lambda: registry)
    monkeypatch.setattr(subagent_router, "_get_accessible_conversation", AsyncMock())
    return registry


async def invoke(service, *, conversation_id="conversation", run_id="exec-a"):
    return await subagent_router.cancel_subagent_execution(
        execution_id=run_id,
        request=SimpleNamespace(),
        db=SimpleNamespace(),
        body=subagent_router.CancelSubAgentRequest(conversation_id=conversation_id),
        current_user=SimpleNamespace(id="user-1"),
        subagent_control=SimpleNamespace(service=service),
    )


@pytest.mark.unit
async def test_http_cancel_is_request_until_owner_acknowledges(registry_boundary):
    service = SimpleNamespace(request_cancel=AsyncMock())
    response = await invoke(service)
    assert response.cancel_requested is True
    assert response.cancelled is False
    run = registry_boundary.get_run("conversation", "exec-a")
    assert run.status.value == "running"
    assert run.metadata["cancel_requested"] is True
    registry_boundary.mark_cancelled("conversation", "exec-a", reason="owner ack")
    response = await invoke(service)
    assert response.cancelled is True
    assert service.request_cancel.await_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "conversation_id,run_id,status_code", [(None, "exec-a", 400), ("conversation", "unknown", 404)]
)
async def test_unknown_scope_or_run_cannot_send_signal(
    registry_boundary, conversation_id, run_id, status_code
):
    service = SimpleNamespace(request_cancel=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await invoke(service, conversation_id=conversation_id, run_id=run_id)
    assert exc.value.status_code == status_code
    service.request_cancel.assert_not_awaited()
    assert (
        registry_boundary.get_run("conversation", "exec-a").metadata.get("cancel_requested")
        is not True
    )


@pytest.mark.unit
async def test_inaccessible_conversation_cannot_send_signal(monkeypatch, registry_boundary):
    monkeypatch.setattr(
        subagent_router,
        "_get_accessible_conversation",
        AsyncMock(side_effect=HTTPException(status_code=404, detail="Conversation not found")),
    )
    service = SimpleNamespace(request_cancel=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await invoke(service)
    assert exc.value.status_code == 404
    service.request_cancel.assert_not_awaited()
    assert (
        registry_boundary.get_run("conversation", "exec-a").metadata.get("cancel_requested")
        is not True
    )
