"""User controls are scoped, durable notifications, never action retries."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from src.infrastructure.agent.native_computer_use.store import (
    DeviceBridgeError,
    control_key,
    request_key,
)
from src.infrastructure.agent.tools.result import ToolControlOutcome
from src.tests.integration.agent.test_native_computer_bridge import (
    bridge as _bridge,
    start_request,
)

pytestmark = pytest.mark.integration
bridge = _bridge


def result_frame(request_id, generation=None, status="user_paused", **changes):
    value = {
        "request_id": request_id,
        "output_json": json.dumps(
            {"type": "computer_use_control", "status": status, "retry_allowed": False}
        ),
        "control_outcome": status,
        "is_error": False,
        "media": [],
    }
    if generation is not None:
        value["control_generation"] = generation
    return {**value, **changes}


def state_frame(request_id, generation, state="resumed", **changes):
    return {
        "request_id": request_id,
        "session_id": "session",
        "control_generation": generation,
        "state": state,
        **changes,
    }


async def claimed(bridge):
    task, request_id = await start_request(bridge)
    await bridge.claim(request_id, user_id="u", device_id="d")
    return task, request_id


@pytest.mark.parametrize("state", ["resumed", "stopped"])
@pytest.mark.parametrize("early", [False, True])
async def test_control_before_or_after_result_wakes_exact_pause_without_replay(
    bridge, state, early
):
    task, request_id = await claimed(bridge)
    generation = str(uuid4())
    notification = state_frame(request_id, generation, state)
    if early:
        await bridge.receive_control_state("connection", notification)
    await bridge.receive_result("connection", result_frame(request_id, generation))
    result = await task
    assert result.control_outcome is ToolControlOutcome.USER_PAUSED
    assert result.is_error is False and result.attachments == []
    waiter = asyncio.create_task(result.control_wait())
    if not early:
        await asyncio.sleep(0)
        assert not waiter.done()
        await bridge.receive_control_state("connection", notification)
    outcome = await asyncio.wait_for(waiter, 1)
    assert outcome == (ToolControlOutcome.USER_STOPPED if state == "stopped" else None)
    assert len(await bridge.redis.xrange(control_key("connection"))) == 1
    stored = await bridge.read(request_key(request_id))
    assert stored["status"] == "completed" and not stored.get("cancelled")


async def test_stale_early_notification_does_not_wake_new_generation(bridge):
    task, request_id = await claimed(bridge)
    old, current = str(uuid4()), str(uuid4())
    await bridge.receive_control_state("connection", state_frame(request_id, old))
    await bridge.receive_result("connection", result_frame(request_id, current))
    result = await task
    waiter = asyncio.create_task(result.control_wait())
    await asyncio.sleep(0)
    assert not waiter.done()
    with pytest.raises(DeviceBridgeError, match="generation_mismatch"):
        await bridge.receive_control_state("connection", state_frame(request_id, old))
    # A stale early candidate must not poison the eventual correct notification.
    await bridge.receive_control_state("connection", state_frame(request_id, current))
    assert await asyncio.wait_for(waiter, 1) is None


@pytest.mark.parametrize(
    "connection,changes", [("foreign", {}), ("connection", {"session_id": "other"})]
)
async def test_foreign_connection_or_session_cannot_resume(bridge, connection, changes):
    task, request_id = await claimed(bridge)
    generation = str(uuid4())
    with pytest.raises(DeviceBridgeError, match="access_denied"):
        await bridge.receive_control_state(
            connection, state_frame(request_id, generation, **changes)
        )
    await bridge.cancel_request(request_id)
    assert (await task).is_error


@pytest.mark.parametrize("cancel", ["request", "run", "device", "session"])
async def test_cancel_wakes_wait_and_late_resume_is_rejected(bridge, cancel):
    task, request_id = await claimed(bridge)
    generation = str(uuid4())
    await bridge.receive_result("connection", result_frame(request_id, generation))
    result = await task
    waiter = asyncio.create_task(result.control_wait())
    await asyncio.sleep(0)
    scope = {"user_id": "u", "tenant_id": "t", "project_id": "p"}
    if cancel == "request":
        await bridge.cancel_request(request_id)
    elif cancel == "run":
        await bridge.cancel_run("run", **scope)
    elif cancel == "device":
        await bridge.cancel_device(connection_id="connection", device_id="d", **scope)
    else:
        await bridge.cancel_session("run", session_id="session", **scope)
    with pytest.raises(DeviceBridgeError, match="control_cancelled"):
        await asyncio.wait_for(waiter, 1)
    with pytest.raises(DeviceBridgeError, match="access_denied"):
        await bridge.receive_control_state("connection", state_frame(request_id, generation))


@pytest.mark.parametrize(
    "changes",
    [
        {"is_error": True},
        {"control_generation": None},
        {"control_generation": "invalid"},
        {"control_outcome": "permission_denied"},
        {
            "output_json": '{"type":"computer_use_control","status":"user_stopped","retry_allowed":false}'
        },
        {"output_json": '{"type":"computer_use_control","status":"user_paused","retry_allowed":0}'},
        {"media": [{"artifact_id": "img", "mime_type": "image/png", "size_bytes": 10}]},
    ],
)
async def test_malformed_control_cannot_hide_failure_or_media(bridge, changes):
    task, request_id = await claimed(bridge)
    with pytest.raises(DeviceBridgeError):
        await bridge.receive_result("connection", result_frame(request_id, str(uuid4()), **changes))
    await bridge.cancel_request(request_id)
    assert (await task).is_error


async def test_output_shape_without_transport_discriminant_is_not_control(bridge):
    task, request_id = await claimed(bridge)
    frame = result_frame(request_id, status="user_stopped")
    frame.pop("control_outcome")
    await bridge.receive_result("connection", frame)
    result = await task
    assert result.control_outcome is None and result.control_wait is None


async def test_user_stopped_is_non_error_but_not_successful_action(bridge):
    task, request_id = await claimed(bridge)
    await bridge.receive_result("connection", result_frame(request_id, status="user_stopped"))
    result = await task
    assert result.control_outcome is ToolControlOutcome.USER_STOPPED
    assert result.control_wait is None and not result.is_error
    assert json.loads(result.output)["retry_allowed"] is False


async def test_disconnected_device_cannot_notify_or_resume_cached_pause(bridge):
    task, request_id = await claimed(bridge)
    generation = str(uuid4())
    await bridge.receive_result("connection", result_frame(request_id, generation))
    result = await task
    await bridge.devices.disconnect("connection")
    with pytest.raises(DeviceBridgeError, match="device_disconnected"):
        await result.control_wait()
    with pytest.raises(DeviceBridgeError, match="device_disconnected"):
        await bridge.receive_control_state("connection", state_frame(request_id, generation))
