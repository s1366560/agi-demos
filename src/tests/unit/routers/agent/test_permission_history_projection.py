"""Replay the real permission event and persisted response contracts."""

import pytest

from src.domain.events.agent_events import AgentPermissionAskedEvent
from src.domain.model.agent.hitl.hitl_request import HITLRequest, HITLRequestStatus, HITLRequestType
from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    _build_hitl_status_map,
    _build_permission_asked,
)
from src.infrastructure.agent.hitl.utils import summarize_hitl_response


@pytest.mark.unit
@pytest.mark.parametrize(
    "action,granted", [("allow", True), ("allow_always", True), ("deny", False)]
)
def test_replay_formal_permission_response(action: str, granted: bool) -> None:
    response, metadata = summarize_hitl_response(
        "permission", {"action": action, "granted": granted}
    )
    record = HITLRequest(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        question="Allow write?",
        request_type=HITLRequestType.CLARIFICATION,
        id="perm_93af798b",
        status=HITLRequestStatus.ANSWERED,
        response=response,
        response_metadata=metadata,
        metadata={
            "hitl_type": "permission",
            "tool_name": "write",
            "action": "execute",
            "allow_remember": False,
            "description": "Write a file",
            "details": {"input": {"api_key": "DO_NOT_PROJECT"}},
        },
    )
    event = AgentPermissionAskedEvent(
        request_id=record.id,
        permission="write",
        patterns=["write"],
        metadata={"tool": "write", "input": {"api_key": "DO_NOT_PROJECT"}},
    ).model_dump()
    result = _build_permission_asked(event, {}, _build_hitl_status_map([record]))
    assert result["answered"] is True
    assert result["granted"] is granted
    assert result["toolName"] == "write"
    assert result["resource"] == "write"
    assert result["action"] == "execute"
    assert result["allowRemember"] is False
    assert "DO_NOT_PROJECT" not in str(result)


@pytest.mark.unit
@pytest.mark.parametrize(
    "response,metadata,expected",
    [
        ("unknown", {}, None),
        ("true", {}, True),
        ("false", {}, False),
        (None, {"granted": True}, True),
        (None, {"granted": "true"}, None),
        ("deny", {"granted": True}, None),
        ("allow", {"granted": False}, None),
    ],
)
def test_legacy_and_unknown_permission_responses(response, metadata, expected) -> None:
    result = _build_permission_asked(
        {"request_id": "p", "tool_name": "legacy", "resource": "file"},
        {},
        {"p": {"status": "answered", "response": response, "response_metadata": metadata}},
    )
    assert result["granted"] is expected
    assert result["toolName"] == "legacy"
    assert result["resource"] == "file"


@pytest.mark.unit
def test_pending_permission_does_not_infer_approval() -> None:
    result = _build_permission_asked(
        {"request_id": "p"},
        {},
        {"p": {"status": "pending", "response": "allow", "response_metadata": {}}},
    )
    assert result["granted"] is None
    assert result["answered"] is False
