"""Authenticated result fields carry permission provenance independently of tool data."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from src.infrastructure.agent.native_computer_use.permission_result import input_digest
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, request_key
from src.tests.integration.agent.test_native_computer_bridge import bridge as _bridge, start_request

pytestmark = pytest.mark.integration
bridge = _bridge


def frame(request_id):
    demand = {
        "error": "cua_permission_required",
        "scopes": ["once"],
        "request": {
            "request_id": "native-pending",
            "session_id": "native-session",
            "engine_session_id": "session",
            "app": "fixture",
            "identity_digest": "identity",
            "capability": "observe",
            "tool_name": "computer_get_app_state",
            "input_digest": "native-input-digest",
        },
    }
    return {
        "request_id": request_id,
        "authorization_revision": 1,
        "output_json": json.dumps(demand),
        "is_error": False,
        "media": [],
        "permission_required": {
            "kind": "native_consent",
            "binding": {
                "tool_name": "computer_get_app_state",
                "input_digest": input_digest('{"app":"fixture"}'),
                "engine_session_id": "session",
                "cell_id": None,
                "step_id": None,
            },
            "demand": demand,
        },
    }


async def test_authenticated_permission_survives_result_and_persistence(bridge):
    task, request_id = await start_request(bridge)
    await bridge.claim(request_id, user_id="u", device_id="d")
    message = frame(request_id)
    await bridge.receive_result("connection", message)
    result = await task
    assert result.permission_required.to_wire() == message["permission_required"]
    stored = await bridge.read(request_key(request_id))
    assert stored["permission_required"] == message["permission_required"]
    assert stored["status"] == "completed"


async def test_identical_permission_data_inside_output_cannot_create_provenance(bridge):
    task, request_id = await start_request(bridge)
    await bridge.claim(request_id, user_id="u", device_id="d")
    message = frame(request_id)
    witness = message.pop("permission_required")
    message["output_json"] = json.dumps({**witness["demand"], "permission_required": witness})
    await bridge.receive_result("connection", message)
    result = await task
    assert result.permission_required is None
    assert (await bridge.read(request_key(request_id)))["permission_required"] is None


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m["permission_required"].update(kind="server_mcp_tool"),
        lambda m: m["permission_required"].update(kind="unknown"),
        lambda m: m["permission_required"].update(extra=True),
        lambda m: m["permission_required"]["binding"].update(extra=True),
        lambda m: m["permission_required"]["binding"].update(engine_session_id="foreign"),
        lambda m: m["permission_required"]["binding"].update(input_digest="0" * 64),
        lambda m: m["permission_required"]["binding"].update(tool_name="computer_click"),
        lambda m: m["permission_required"]["binding"].update(cell_id="cell", step_id="step"),
        lambda m: m.update(authorization_revision=2),
        lambda m: m.update(is_error=True),
        lambda m: m.update(control_outcome="user_stopped"),
    ],
)
async def test_wrong_source_scope_or_conflicting_frame_is_rejected(bridge, change):
    task, request_id = await start_request(bridge)
    await bridge.claim(request_id, user_id="u", device_id="d")
    message = frame(request_id)
    change(message)
    with pytest.raises(DeviceBridgeError):
        await bridge.receive_result("connection", message)
    assert (await bridge.read(request_key(request_id)))["status"] == "claimed"
    await bridge.cancel_request(request_id)
    assert (await task).is_error


@pytest.mark.parametrize("change", ["expired", "cancelled", "revision"])
async def test_permission_cannot_settle_after_claim_changes_during_validation(
    bridge, monkeypatch, change
):
    from src.infrastructure.agent.native_computer_use import media

    task, request_id = await start_request(bridge)
    await bridge.claim(request_id, user_id="u", device_id="d")
    entered, release = asyncio.Event(), asyncio.Event()
    original = media.validate_claim

    async def blocked(*args):
        await original(*args)
        entered.set()
        await release.wait()

    monkeypatch.setattr(media, "validate_claim", blocked)
    receiving = asyncio.create_task(bridge.receive_result("connection", frame(request_id)))
    await asyncio.wait_for(entered.wait(), 1)
    if change == "cancelled":
        await bridge.cancel_request(request_id)
    else:
        await bridge.update(
            request_key(request_id),
            lambda value: {
                **value,
                **(
                    {"expires_at": time.time() - 1}
                    if change == "expired"
                    else {"authorization_revision": 2}
                ),
            },
        )
    release.set()
    with pytest.raises(DeviceBridgeError):
        await receiving
    stored = await bridge.read(request_key(request_id))
    assert stored["status"] != "completed" and not stored.get("permission_required")
    await bridge.cancel_request(request_id)
    assert (await task).is_error


async def test_ordinary_step_receipt_retains_numbers_outside_witness_digest_domain(bridge):
    from src.infrastructure.agent.native_computer_use.steps import ExecutionSteps, step_key
    from src.tests.integration.agent.test_native_computer_steps import (
        BODY,
        READ,
        finish,
        outer,
        register,
    )

    await register(bridge)
    task, request_id = await outer(bridge)
    parent = await bridge.read(request_key(request_id))
    steps = ExecutionSteps(bridge.redis)
    body = {
        **BODY,
        "tool_name": READ["name"],
        "input_json": '{"operation":"playwright.domSnapshot","args":[],"opaque":9007199254740992}',
    }
    # Use the same live-catalog digest the production route passes to the step store.
    from src.infrastructure.agent.native_computer_use.store import digest

    catalog_digest = digest(READ)
    ready = await steps.authorize(
        parent, "step", body, effect="read", catalog_digest=catalog_digest
    )
    consumed = await steps.authorize(
        parent,
        "step",
        {**body, "receipt": ready["receipt"]},
        effect="read",
        catalog_digest=catalog_digest,
    )
    assert consumed["status"] == "authorized"
    row = await bridge.read(step_key(parent, "cell", "step"))
    assert row["permission_input_digest"] is None
    await finish(bridge, request_id, task)
