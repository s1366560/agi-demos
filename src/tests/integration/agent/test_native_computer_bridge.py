"""Real Redis transport tests with private, disposable keys and no device input."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from src.infrastructure.agent.native_computer_use import devices, media, store
from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
from src.infrastructure.agent.native_computer_use.contracts import CallAuthorization, DeviceScope
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, control_key

pytestmark = pytest.mark.integration
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOioAAAAASUVORK5CYII="
)
DEFINITION = {
    "name": "computer_get_app_state",
    "description": "Observe a window",
    "inputSchema": {
        "type": "object",
        "properties": {"app": {"type": "string"}},
        "required": ["app"],
        "additionalProperties": False,
    },
}


@pytest_asyncio.fixture(loop_scope="function")
async def bridge(monkeypatch):
    prefix = f"test:computer-use:{uuid4()}"
    for module in (store, devices, media):
        monkeypatch.setattr(module, "PREFIX", prefix)
    redis = Redis.from_url(
        os.getenv("NATIVE_CUA_TEST_REDIS_URL", "redis://localhost:6379"), decode_responses=True
    )
    try:
        await redis.ping()
    except Exception:
        await redis.aclose()
        pytest.skip("Redis integration environment unavailable")
    broker = NativeComputerBroker(redis, timeout=2)
    await broker.devices.register(
        DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d"),
        "connection",
        [DEFINITION],
    )
    yield broker
    keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()


def authorization(**changes):
    value = CallAuthorization(
        user_id="u",
        tenant_id="t",
        project_id="p",
        device_id=None,
        conversation_id="conversation",
        run_id="run",
        session_id="session",
        round=0,
        permission_profile="read_only",
        authorization_revision=1,
        plan_version_id=None,
        approved_tools=(),
        call_id="call",
    )
    return replace(value, **changes)


async def start_request(bridge, auth=None):
    task = asyncio.create_task(
        bridge.request(auth or authorization(), DEFINITION["name"], {"app": "fixture"})
    )
    messages = await bridge.redis.xread({control_key("connection"): "0-0"}, block=1000)
    assert messages
    request_id = messages[0][1][-1][1]["request_id"]
    return task, request_id


async def settle(bridge, request_id, *, images=False):
    await bridge.claim(request_id, user_id="u", device_id="d")
    await bridge.receive_result(
        "connection",
        {
            "request_id": request_id,
            "output_json": json.dumps({"observation_id": "fresh"}),
            "is_error": False,
            "media": [{"artifact_id": "image", "mime_type": "image/png", "size_bytes": len(PNG)}]
            if images
            else [],
        },
    )
    if images:
        await bridge.receive_chunk(
            "connection",
            {
                "request_id": request_id,
                "artifact_id": "image",
                "mime_type": "image/png",
                "offset": 0,
                "eof": True,
                "data_base64": base64.b64encode(PNG).decode(),
            },
        )


async def test_real_redis_request_claim_and_typed_image_round_trip(bridge):
    task, request_id = await start_request(bridge)
    await settle(bridge, request_id, images=True)
    result = await task
    assert result.attachments[0].content == PNG
    assert result.attachments[0].mime_type == "image/png"
    assert "base64" not in result.output and "iVBOR" not in result.output
    replay = await bridge.request(authorization(), DEFINITION["name"], {"app": "fixture"})
    assert replay.attachments[0].content == PNG
    events = await bridge.redis.xrange(control_key("connection"))
    assert len(events) == 1
    claimed = await bridge.read(store.request_key(request_id))
    assert int(events[0][1]["expires_at"]) == claimed["expires_at"]


async def test_lost_response_never_redispatches_same_call(bridge):
    bridge.timeout = 0.2
    task, request_id = await start_request(bridge)
    await bridge.claim(request_id, user_id="u", device_id="d")
    assert json.loads((await task).output)["error"] == "action_outcome_unknown"
    assert (
        json.loads(
            (await bridge.request(authorization(), DEFINITION["name"], {"app": "fixture"})).output
        )["retry_allowed"]
        is False
    )
    events = await bridge.redis.xrange(control_key("connection"))
    assert [event[1]["type"] for event in events] == ["computer_use_request", "computer_use_cancel"]


async def test_owner_and_device_claims_do_not_consume_legitimate_request(bridge):
    task, request_id = await start_request(bridge)
    for user, device in [("other", "d"), ("u", "other")]:
        with pytest.raises(DeviceBridgeError, match="access_denied"):
            await bridge.claim(request_id, user_id=user, device_id=device)
    await settle(bridge, request_id)
    with pytest.raises(DeviceBridgeError, match="already_claimed"):
        await bridge.claim(request_id, user_id="u", device_id="d")
    assert not (await task).is_error


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_mode", "foreground"),
        ("input_generation", "forged-generation"),
        ("target_pid", 123),
        ("process_id", 123),
    ],
)
async def test_model_cannot_override_native_input_authority(bridge, field, value):
    with pytest.raises(DeviceBridgeError, match="computer_use_invalid_params"):
        await bridge.request(authorization(), DEFINITION["name"], {"app": "fixture", field: value})
    assert await bridge.redis.xlen(control_key("connection")) == 0


async def test_different_round_observes_again_with_same_arguments(bridge):
    task, first = await start_request(bridge)
    await settle(bridge, first)
    await task
    next_task = asyncio.create_task(
        bridge.request(authorization(round=1), DEFINITION["name"], {"app": "fixture"})
    )
    events = await bridge.redis.xread(
        {control_key("connection"): (await bridge.redis.xrange(control_key("connection")))[-1][0]},
        block=1000,
    )
    second = events[0][1][0][1]["request_id"]
    assert second != first
    await settle(bridge, second)
    assert not (await next_task).is_error


async def test_cancel_stops_pending_and_completed_session_requests(bridge):
    task, request_id = await start_request(bridge)
    await settle(bridge, request_id)
    await task
    await bridge.cancel_run("run", user_id="u", tenant_id="t", project_id="p")
    events = await bridge.redis.xrange(control_key("connection"))
    assert events[-1][1] == {"type": "computer_use_cancel", "request_id": request_id}
    pending_task = asyncio.create_task(
        bridge.request(authorization(call_id="pending"), DEFINITION["name"], {"app": "fixture"})
    )
    await asyncio.sleep(0.05)
    pending_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_task
    events = await bridge.redis.xrange(control_key("connection"))
    assert events[-1][1]["type"] == "computer_use_cancel"


async def test_registration_owner_isolation_and_exclusive_connection(bridge):
    assert await bridge.describe_tools(tenant_id="t", project_id="p", user_id="other") == []
    assert await bridge.describe_tools(tenant_id="t", project_id="other", user_id="u") == []
    assert await bridge.describe_tools(tenant_id="t", project_id="p") == []
    assert await bridge.describe_tools(tenant_id="t", project_id="p", user_id="u") == [DEFINITION]
    with pytest.raises(DeviceBridgeError, match="device_busy"):
        await bridge.devices.register(
            DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d"),
            "intruder",
            [DEFINITION],
        )
    await bridge.devices.heartbeat("connection")
    await bridge.devices.disconnect("connection")
    with pytest.raises(DeviceBridgeError, match="disconnected"):
        await bridge.request(authorization(), DEFINITION["name"], {"app": "fixture"})


async def test_media_wrong_owner_and_offset_are_rejected_without_advancing(bridge):
    task, request_id = await start_request(bridge)
    await bridge.claim(request_id, user_id="u", device_id="d")
    header = {
        "request_id": request_id,
        "output_json": "{}",
        "is_error": False,
        "media": [{"artifact_id": "image", "mime_type": "image/png", "size_bytes": len(PNG)}],
    }
    with pytest.raises(DeviceBridgeError, match="access_denied"):
        await bridge.receive_result("other", header)
    await bridge.receive_result("connection", header)
    chunk = {
        "request_id": request_id,
        "artifact_id": "image",
        "mime_type": "image/png",
        "offset": 1,
        "eof": True,
        "data_base64": base64.b64encode(PNG).decode(),
    }
    with pytest.raises(DeviceBridgeError, match="offset_mismatch"):
        await bridge.receive_chunk("connection", chunk)
    with pytest.raises(DeviceBridgeError, match="access_denied"):
        await bridge.receive_chunk("other", {**chunk, "offset": 0})
    await bridge.receive_chunk("connection", {**chunk, "offset": 0})
    assert (await task).attachments[0].content == PNG


async def test_ambiguous_device_requires_explicit_agent_selection(bridge):
    await bridge.devices.register(
        DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="second"),
        "second-connection",
        [DEFINITION],
    )
    result = await bridge.request(authorization(), DEFINITION["name"], {"app": "fixture"})
    assert set(json.loads(result.output)["devices"]) == {"d", "second"}
    task, request_id = await start_request(bridge, authorization(device_id="d"))
    await settle(bridge, request_id)
    assert not (await task).is_error
