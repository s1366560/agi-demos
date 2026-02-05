"""Unit tests for RayHITLHandler."""

from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent.hitl_types import HITLPendingException, HITLType
from src.infrastructure.agent.hitl import ray_hitl_handler
from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler


@pytest.mark.unit
class TestRayHITLHandler:
    """Tests for RayHITLHandler."""

    async def test_request_clarification_persists_and_raises(self, monkeypatch):
        persist_mock = AsyncMock()
        emit_mock = AsyncMock()

        monkeypatch.setattr(ray_hitl_handler, "_persist_hitl_request", persist_mock)
        monkeypatch.setattr(ray_hitl_handler, "_emit_hitl_sse_event", emit_mock)

        handler = RayHITLHandler(
            conversation_id="conv-1",
            tenant_id="tenant-1",
            project_id="project-1",
            message_id="msg-1",
            default_timeout=120.0,
        )

        with pytest.raises(HITLPendingException) as exc_info:
            await handler.request_clarification(
                question="Need clarification?",
                options=["yes", "no"],
                request_id="clar_123",
            )

        assert exc_info.value.request_id == "clar_123"
        assert exc_info.value.hitl_type == HITLType.CLARIFICATION

        persist_mock.assert_awaited_once()
        emit_mock.assert_awaited_once()
        assert persist_mock.call_args.kwargs["request_id"] == "clar_123"
        assert persist_mock.call_args.kwargs["hitl_type"] == HITLType.CLARIFICATION

    async def test_preinjected_response_short_circuits(self, monkeypatch):
        persist_mock = AsyncMock()
        emit_mock = AsyncMock()

        monkeypatch.setattr(ray_hitl_handler, "_persist_hitl_request", persist_mock)
        monkeypatch.setattr(ray_hitl_handler, "_emit_hitl_sse_event", emit_mock)

        handler = RayHITLHandler(
            conversation_id="conv-2",
            tenant_id="tenant-2",
            project_id="project-2",
            preinjected_response={
                "hitl_type": "decision",
                "response_data": {"decision": "approve"},
            },
        )

        result = await handler.request_decision(
            question="Approve?",
            options=["approve", "deny"],
            request_id="deci_123",
        )

        assert result == "approve"
        persist_mock.assert_not_called()
        emit_mock.assert_not_called()
