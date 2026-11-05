"""Continuity requires a consumed enable operation, never guessed JavaScript intent."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.native_computer_use.continuity import require_enable, require_source
from src.infrastructure.agent.native_computer_use.permission_result import input_digest
from src.infrastructure.agent.native_computer_use.steps import step_key
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, request_key

pytestmark = pytest.mark.unit


def source(**changes):
    return {
        "request_id": "request",
        "user_id": "u",
        "tenant_id": "t",
        "project_id": "p",
        "device_id": "d",
        "session_id": "engine",
        "run_id": "run",
        "conversation_id": "c",
        "connection_id": "connection",
        "status": "completed",
        "authorization_revision": 3,
        "tool_name": "computer_locked_use",
        "input_json": '{"enabled":true}',
        **changes,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"cancelled": True},
        {"status": "requested"},
        {"status": "unknown"},
        {"is_error": True},
        {"control_outcome": "user_paused"},
        {"permission_required": {}},
        {"session_id": "foreign"},
    ],
)
def test_continuity_rejects_inactive_or_foreign_source(change):
    with pytest.raises(DeviceBridgeError):
        require_source(source(**change), user_id="u", device_id="d", session_id="engine")


async def test_direct_enable_survives_original_invocation_expiry_without_mutation():
    value = source(expires_at=1)
    assert require_source(value, user_id="u", device_id="d", session_id="engine") is value
    await require_enable(AsyncMock(), value, cell_id=None, step_id=None, parent_request_id=None)
    assert value["expires_at"] == 1


@pytest.mark.parametrize(
    "arguments", ['{"enabled":false}', '{"enabled":1}', "{}", '{"enabled":true,"ttl_ms":99999}']
)
async def test_only_exact_enable_can_create_continuity(arguments):
    with pytest.raises(DeviceBridgeError):
        await require_enable(
            AsyncMock(),
            source(input_json=arguments),
            cell_id=None,
            step_id=None,
            parent_request_id=None,
        )


async def test_repl_requires_exact_consumed_enable_and_same_revision():
    parent = source(
        tool_name="cua_repl_js",
        input_json='{"code":"await cua.computer.lockedUse({enabled:true})"}',
    )
    step = {
        **parent,
        "tool_name": "computer_locked_use",
        "status": "consumed",
        "current_request_id": "request",
        "permission_input_digest": input_digest('{"enabled":true}'),
    }
    rows = {request_key("request"): parent, step_key(parent, "cell", "step"): step}
    store = AsyncMock()
    store.read.side_effect = lambda key: rows.get(key)
    await require_enable(store, parent, cell_id="cell", step_id="step", parent_request_id=None)
    for changed in (
        {"status": "ready"},
        {"status": "released"},
        {"authorization_revision": 4},
        {"tool_name": "computer_click"},
        {"current_request_id": "foreign"},
        {"permission_input_digest": input_digest('{"enabled":false}')},
        {"run_id": "foreign"},
    ):
        rows[step_key(parent, "cell", "step")] = {**step, **changed}
        with pytest.raises(DeviceBridgeError):
            await require_enable(
                store, parent, cell_id="cell", step_id="step", parent_request_id=None
            )
