"""Automatic approval provenance is scoped and never inferred for manual responses."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers.agent.automatic_permission_response import (
    annotate_automatic_permission_response,
)
from src.infrastructure.agent.hitl.utils import summarize_hitl_response

pytestmark = pytest.mark.unit


def record(metadata=None):
    return SimpleNamespace(
        request_type="clarification",
        metadata={"hitl_type": "permission", **(metadata or {})},
        conversation_id="c",
        tenant_id="t",
        project_id="p",
    )


@pytest.mark.parametrize("mode,preset", [("full_access", "full"), ("auto_edit", "relaxed")])
async def test_canonical_automatic_approval_persists_verified_provenance(mode, preset):
    db = SimpleNamespace(scalar=AsyncMock(return_value={"approval_mode": mode}))
    result = await annotate_automatic_permission_response(
        db,
        hitl_request=record({"permission_type": "write"}),
        approval_mode=mode,
        response_data={"action": "allow", "granted": True, "scope": "once"},
    )
    assert result["auto_approved"] is True
    assert summarize_hitl_response("permission", result) == (
        "allow",
        {"auto_approved": True, "preset": preset},
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"native_binding": None},
        {"native_binding": {}},
        {"native_binding": "invalid"},
        {"permission_type": "computer_use"},
        {"decision": {"target": {"kind": "computer_app"}}},
        {"decision": {"target": {"kind": "device_mcp_tool"}}},
    ],
)
async def test_native_permissions_never_receive_automatic_provenance(metadata):
    db = SimpleNamespace(scalar=AsyncMock())
    with pytest.raises(ValueError):
        await annotate_automatic_permission_response(
            db,
            hitl_request=record(metadata),
            approval_mode="full_access",
            response_data={"action": "allow", "granted": True, "scope": "once"},
        )
    db.scalar.assert_not_awaited()


@pytest.mark.parametrize(
    "mode,metadata,response",
    [
        (
            "auto_edit",
            {"permission_type": "read"},
            {"action": "allow", "granted": True, "scope": "once"},
        ),
        ("full_access", {}, {"action": "deny", "granted": False, "scope": "once"}),
        ("full_access", {}, {"action": "allow", "granted": True, "scope": "session"}),
    ],
)
async def test_denial_scope_and_nonedit_permissions_cannot_be_marked_automatic(
    mode, metadata, response
):
    with pytest.raises(ValueError):
        await annotate_automatic_permission_response(
            SimpleNamespace(scalar=AsyncMock()),
            hitl_request=record(metadata),
            approval_mode=mode,
            response_data=response,
        )


async def test_stale_canonical_mode_rejects_automatic_and_manual_forgery_is_removed():
    db = SimpleNamespace(scalar=AsyncMock(return_value={"approval_mode": "ask"}))
    response = {
        "action": "allow",
        "granted": True,
        "scope": "once",
        "auto_approved": True,
        "preset": "full",
    }
    with pytest.raises(ValueError):
        await annotate_automatic_permission_response(
            db, hitl_request=record(), approval_mode="full_access", response_data=response
        )
    result = await annotate_automatic_permission_response(
        db, hitl_request=record(), approval_mode=None, response_data=response
    )
    assert result == {"action": "allow", "granted": True, "scope": "once"}
    assert summarize_hitl_response("permission", result) == ("allow", None)


def test_history_auto_provenance_is_preserved_but_denied_cards_remain_manual():
    from src.infrastructure.adapters.primary.web.routers.agent.messages import (
        _build_permission_replied,
    )
    from src.infrastructure.adapters.primary.web.routers.agent.permission_history_projection import (
        permission_history_item,
    )

    status = {
        "r": {
            "status": "answered",
            "response": "allow",
            "response_metadata": {"auto_approved": True, "preset": "full"},
        }
    }
    card = permission_history_item({"request_id": "r"}, {}, status)
    assert card["autoApproved"] is True
    assert card["auto_approved"] is True
    assert card["preset"] == "full"
    for granted in [True, False]:
        reply = _build_permission_replied(
            {"request_id": "r", "granted": granted, "auto_approved": True, "preset": "full"}
        )
        assert reply["autoApproved"] is granted
        assert reply["preset"] == ("full" if granted else None)


async def test_real_persisted_permission_contract_passes_annotation_and_rest_strict_validation():
    from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestType
    from src.infrastructure.adapters.primary.web.routers.agent.hitl import (
        _validate_and_summarize_hitl_response,
    )
    from src.infrastructure.adapters.primary.web.routers.agent.schemas import HITLResponseRequest

    persisted = HITLRequest(
        id="permission",
        request_type=HITLRequestType.CLARIFICATION,
        conversation_id="conversation",
        tenant_id="tenant",
        project_id="project",
        question="Run declared tool",
        metadata={
            "hitl_type": "permission",
            "permission_type": "bash",
            "tool_name": "bash",
            "action": "execute",
            "risk_level": "medium",
        },
    )
    command = HITLResponseRequest(
        request_id=persisted.id,
        hitl_type="permission",
        approval_mode="full_access",
        response_data={"action": "allow", "granted": True, "scope": "once"},
    )
    command.response_data = await annotate_automatic_permission_response(
        SimpleNamespace(scalar=AsyncMock(return_value={"approval_mode": "full_access"})),
        hitl_request=persisted,
        approval_mode=command.approval_mode,
        response_data=command.response_data,
    )
    assert _validate_and_summarize_hitl_response(
        hitl_request=persisted, request=command, tenant_id="tenant"
    ) == (
        "permission",
        "allow",
        {"auto_approved": True, "preset": "full"},
    )
