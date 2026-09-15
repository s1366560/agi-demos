"""Active clarification tools retain mutation metadata and peer admission ordering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.workspace.wtp_envelope import WtpEnvelope, WtpVerb
from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.agent.tools import workspace_clarification as clar
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.plugins.v2.agent_orchestration_tools import _AGENT_ORCHESTRATION_TOOLS_V2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


def test_active_clarification_tool_contracts_declare_message_write():
    for tool in (
        clar.workspace_request_clarification_tool,
        clar.workspace_respond_clarification_tool,
    ):
        assert tool in _AGENT_ORCHESTRATION_TOOLS_V2
        converted = convert_tools({tool.name: tool})
        assert len(converted) == 1
        assert converted[0].permission == "write"


@pytest.mark.parametrize(
    "verb,denied",
    [
        (WtpVerb.TASK_CLARIFY_REQUEST, False),
        (WtpVerb.TASK_CLARIFY_REQUEST, True),
        (WtpVerb.TASK_CLARIFY_RESPONSE, False),
    ],
)
async def test_clarification_real_orchestrator_preflight_precedes_peer_delivery(
    monkeypatch, verb, denied
):
    bus = SimpleNamespace(send_message=AsyncMock(return_value="actual-message"))
    admission = object()
    preflight = AsyncMock(return_value=admission)
    executor = AsyncMock()
    if denied:
        preflight.side_effect = RuntimeV2Error("peer_session_permission_denied", "Denied")
    orchestrator = AgentOrchestrator(
        agent_registry=Mock(),
        session_registry=Mock(),
        spawn_manager=SimpleNamespace(
            get_record=AsyncMock(
                return_value=SimpleNamespace(mode=SpawnMode.SESSION, project_id="project")
            )
        ),
        message_bus=bus,
        session_turn_executor=executor,
        session_turn_preflight=preflight,
    )
    orchestrator._resolve_message_sender = AsyncMock(
        return_value=SimpleNamespace(id="sender", name="Sender")
    )
    orchestrator._resolve_message_target = AsyncMock(return_value=SimpleNamespace(id="peer"))
    orchestrator._resolve_message_session_id = AsyncMock(return_value="peer-session")
    orchestrator._validate_message_sender_session = AsyncMock()
    monkeypatch.setattr(clar, "_current_agent_orchestrator_v2", lambda: orchestrator)
    context = ToolContext(
        session_id="parent-session",
        message_id="message",
        call_id="call",
        agent_name="sender",
        conversation_id="parent-session",
        project_id="project",
        tenant_id="tenant",
        user_id="owner",
    )
    envelope = WtpEnvelope(
        verb=verb,
        workspace_id="workspace",
        task_id="task",
        attempt_id="attempt",
        correlation_id="correlation",
        payload={"question": "Clarify scope"}
        if verb is WtpVerb.TASK_CLARIFY_REQUEST
        else {"answer": "Use approved scope"},
    )
    result, _ = await clar._send_envelope_generic(context, envelope, to_agent_id="peer")
    assert result.is_error == denied
    if denied:
        bus.send_message.assert_not_awaited()
        executor.assert_not_awaited()
    elif verb is WtpVerb.TASK_CLARIFY_REQUEST:
        preflight.assert_awaited_once()
        executor.assert_awaited_once()
        request = executor.await_args.args[0]
        assert request.admission is admission
        assert request.child_session_id == "peer-session"
        assert request.sender_agent_id == "sender"
        assert bus.send_message.await_args.kwargs["message_type"] is AgentMessageType.REQUEST
    else:
        preflight.assert_not_awaited()
        executor.assert_not_awaited()
        assert bus.send_message.await_args.kwargs["message_type"] is AgentMessageType.RESPONSE
