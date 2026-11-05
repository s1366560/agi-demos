"""Cloud browser identity comes from host fields after child lease admission."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
from src.infrastructure.agent.native_computer_use.browser_scope import browser_scope
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError

pytestmark = pytest.mark.unit


def call(**changes):
    return {
        "conversation_id": "main",
        "run_id": "parent",
        "session_id": "engine",
        "user_id": "user",
        "device_id": "device",
        "status": "requested",
        "expires_at": time.time() + 60,
        **changes,
    }


def test_root_scope_cannot_be_changed_by_javascript_arguments():
    value = call(input_json='{"child_run_id":"forged","browser_scope":{"is_child":true}}')
    assert browser_scope(value) == {
        "execution_id": "parent",
        "main_conversation_id": "main",
        "parent_run_id": "parent",
        "engine_session_id": "engine",
        "is_child": False,
    }


def test_child_scope_preserves_execution_and_parent_identity():
    result = browser_scope(call(child_run_id="child", child_owner_digest="owner-witness"))
    assert result["execution_id"] == "child"
    assert result["main_conversation_id"] == "main"
    assert result["parent_run_id"] == "parent"
    assert result["engine_session_id"] == "engine"
    assert result["is_child"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"child_run_id": "child"},
        {"child_run_id": "parent", "child_owner_digest": "witness"},
        {"child_run_id": "", "child_owner_digest": "witness"},
    ],
)
def test_incomplete_or_conflicting_child_identity_is_rejected(changes):
    with pytest.raises(DeviceBridgeError):
        browser_scope(call(**changes))


async def test_claim_exposes_verified_scope_without_owner_witness():
    broker = NativeComputerBroker(AsyncMock())
    value = call(child_run_id="child", child_owner_digest="private-witness")

    async def update(_key, change):
        return change(value)

    broker.update = AsyncMock(side_effect=update)
    claimed = await broker.claim("request", user_id="user", device_id="device")
    assert claimed["browser_scope"]["execution_id"] == "child"
    assert "child_owner_digest" not in claimed
    assert "status" not in claimed
