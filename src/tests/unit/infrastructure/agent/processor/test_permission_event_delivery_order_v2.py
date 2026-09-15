"""Prove request delivery precedes waiting on the real coordinator response."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.events.agent_events import AgentPermissionAskedEvent
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.hitl.coordinator import (
    HITLCoordinator,
    ResolveResult,
    resolve_by_request_id,
)
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)


@pytest.mark.unit
async def test_real_coordinator_permission_event_is_delivered_before_response() -> None:
    tool = ToolDefinition(
        name="delivery_probe",
        description="No model or real side effects",
        parameters={},
        permission="write",
        execute=AsyncMock(),
    )
    processor = SessionProcessor(config=ProcessorConfig(model="never-called"), tools=[tool])
    coordinator = HITLCoordinator(
        conversation_id="delivery-order-conversation",
        tenant_id="delivery-order-tenant",
        project_id="delivery-order-project",
    )
    processor._hitl_coordinator = coordinator
    processor._langfuse_context = {
        "conversation_id": coordinator.conversation_id,
        "tenant_id": coordinator.tenant_id,
        "project_id": coordinator.project_id,
    }
    part = ToolPart(call_id="call", tool=tool.name, status=ToolState.RUNNING)
    events = processor._ask_tool_permission(
        "delivery-order-conversation", "call", tool.name, {"path": "fixture"}, part, tool
    )
    with patch(
        "src.infrastructure.agent.hitl.coordinator._persist_hitl_request", new_callable=AsyncMock
    ) as persist:
        event = await asyncio.wait_for(anext(events), timeout=1)
        assert isinstance(event, AgentPermissionAskedEvent)
        persist.assert_awaited_once()
        assert event.request_id in coordinator.pending_request_ids
        tool.execute.assert_not_awaited()
        assert (
            resolve_by_request_id(
                event.request_id,
                {"action": "allow", "remember": False},
                tenant_id="delivery-order-tenant",
                project_id="delivery-order-project",
                conversation_id="delivery-order-conversation",
            )
            == ResolveResult.RESOLVED
        )
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(events), timeout=1)
        coordinator.cancel_request_if_pending(event.request_id)
        assert coordinator.pending_count == 0
