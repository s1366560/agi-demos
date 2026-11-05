"""Real Redis per-step receipts and resume binding, with no application side effects."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from src.infrastructure.adapters.primary.web.routers.agent import computer_use_steps as routes
from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.steps import ExecutionSteps, step_key
from src.infrastructure.agent.native_computer_use.store import control_key, request_key
from src.tests.integration.agent.test_native_computer_bridge import authorization, bridge as _bridge
from src.tests.integration.agent.test_native_computer_claims import application

pytestmark = pytest.mark.integration
bridge = _bridge
OUTER = {
    "name": "cua_repl_js",
    "description": "Execute a cell with per-operation authority",
    "inputSchema": {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
        "additionalProperties": False,
    },
}
INNER = {
    "name": "browser_write_operation",
    "description": "Browser action",
    "inputSchema": {"type": "object", "x-cua-step-only": True},
}
READ = {**INNER, "name": "browser_read_operation"}
CODE = "await tab.goto('http://fixture.test')"
BODY = {
    "device_id": "d",
    "cell_id": "cell",
    "tool_name": INNER["name"],
    "input_json": json.dumps(
        {"operation": "tab.goto", "args": ["http://fixture.test"], "browserId": "iab", "tabId": "1"}
    ),
    "target": {
        "kind": "browser",
        "id": "iab/1/http://fixture.test",
        "browser_id": "iab",
        "tab_id": "1",
        "url": "http://fixture.test",
    },
}


async def register(bridge):
    bridge.timeout = 30
    await bridge.devices.register(
        DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d"),
        "connection",
        [OUTER, INNER, READ],
    )


async def outer(bridge, call="call", code=CODE, revision=1):
    task = asyncio.create_task(
        bridge.request(
            authorization(call_id=call, authorization_revision=revision),
            "cua_repl_js",
            {"code": code},
        )
    )
    for _ in range(100):
        events = await bridge.redis.xrange(control_key("connection"))
        if len(events) >= (1 if call == "call" else 2):
            request_id = events[-1][1]["request_id"]
            await bridge.claim(request_id, user_id="u", device_id="d")
            return task, request_id
        await asyncio.sleep(0.01)
    raise AssertionError("request was not dispatched")


async def finish(bridge, request_id, task, output=None):
    await bridge.receive_result(
        "connection",
        {
            "request_id": request_id,
            "output_json": json.dumps(output or {}),
            "is_error": False,
            "media": [],
        },
    )
    await task


async def test_pending_step_approval_resumes_only_same_input_and_consumes_once(bridge, monkeypatch):
    await register(bridge)
    task, request_id = await outer(bridge)
    app, _, loader = application(bridge, monkeypatch)
    servers = AsyncMock(return_value=())
    monkeypatch.setattr(routes, "current_agent_servers", servers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        endpoint = f"/api/v1/agent/device/requests/{request_id}/steps/step/authorize"
        response = await client.post(endpoint, json=BODY)
        assert response.status_code == 200, response.text
        pending = response.json()
        assert pending["status"] == "pending" and pending["scopes"] == ["once"]
        assert loader.await_count == 4
        assert servers.await_count == 2
        forged = await client.post(endpoint, json={**BODY, "continuation": {"kind": "hitl"}})
        assert forged.status_code == 422
        await finish(bridge, request_id, task, pending)
        parent = await bridge.read(request_key(request_id))
        stored = await bridge.read(step_key(parent, "cell", "step"))
        binding = {
            **stored,
            "execution_step": pending["request"]["execution_step"],
            "native_request_id": pending["request"]["request_id"],
        }
        binding["authorization_revision"] = 2
        await ExecutionSteps(bridge.redis).resolve_permission(
            binding, True, hitl_request_id="committed-hitl"
        )
        loader.return_value[0].revision = 2
        resumed_task, resumed_id = await outer(bridge, "resume", revision=2)
        endpoint = f"/api/v1/agent/device/requests/{resumed_id}/steps/step/authorize"
        body = {**BODY, "parent_request_id": request_id}
        altered = await client.post(
            endpoint, json={**body, "input_json": json.dumps({"operation": "tab.close"})}
        )
        assert altered.status_code == 409
        ready = await client.post(endpoint, json=body)
        assert ready.status_code == 200, ready.text
        assert ready.json()["status"] == "ready"
        continuation = ready.json()["continuation"]
        assert continuation == {
            "kind": "hitl",
            "hitl_request_id": "committed-hitl",
            "origin_request_id": request_id,
            "previous_authorization_revision": 1,
            "authorization_revision": 2,
            "cell_id": "cell",
            "step_id": "step",
        }
        receipt = ready.json()["receipt"]
        consumed = await client.post(endpoint, json={**body, "receipt": receipt})
        assert consumed.json()["status"] == "authorized"
        assert consumed.json()["continuation"] == continuation
        duplicate = await client.post(endpoint, json={**body, "receipt": receipt})
        assert duplicate.status_code == 409
        released = await client.post(
            endpoint, json={**body, "receipt": receipt, "outcome": "not_sent"}
        )
        assert released.json()["status"] == "released"
        assert "continuation" not in released.json()
        await finish(bridge, resumed_id, resumed_task)


async def test_read_step_rejects_mutating_operation_and_live_parent_cancellation(
    bridge, monkeypatch
):
    await register(bridge)
    task, request_id = await outer(bridge)
    app, _, _ = application(bridge, monkeypatch)
    monkeypatch.setattr(routes, "current_agent_servers", AsyncMock(return_value=()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        endpoint = f"/api/v1/agent/device/requests/{request_id}/steps/read/authorize"
        forged = await client.post(endpoint, json={**BODY, "tool_name": READ["name"]})
        assert forged.status_code == 409
        body = {
            **BODY,
            "tool_name": READ["name"],
            "input_json": json.dumps({"operation": "playwright.domSnapshot"}),
        }
        ready = await client.post(endpoint, json=body)
        assert ready.json()["status"] == "ready"
        await bridge.cancel_request(request_id)
        cancelled = await client.post(endpoint, json={**body, "receipt": ready.json()["receipt"]})
        assert cancelled.status_code == 409
    await task


async def test_catalog_change_cannot_consume_previously_issued_receipt(bridge, monkeypatch):
    await register(bridge)
    task, request_id = await outer(bridge)
    app, _, _ = application(bridge, monkeypatch)
    monkeypatch.setattr(routes, "current_agent_servers", AsyncMock(return_value=()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        endpoint = f"/api/v1/agent/device/requests/{request_id}/steps/read/authorize"
        body = {
            **BODY,
            "tool_name": READ["name"],
            "input_json": json.dumps({"operation": "playwright.domSnapshot"}),
        }
        ready = await client.post(endpoint, json=body)
        assert ready.json()["status"] == "ready"
        await bridge.devices.register(
            DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d"),
            "connection",
            [OUTER, INNER, {**READ, "description": "Changed catalog"}],
        )
        rejected = await client.post(endpoint, json={**body, "receipt": ready.json()["receipt"]})
        assert rejected.status_code == 409
    await finish(bridge, request_id, task)


async def test_dynamic_mcp_uses_exact_current_server_roster_and_mutation_approval(
    bridge, monkeypatch
):
    await register(bridge)
    mcp = {
        "name": "mcp__fixture__opaque",
        "description": "Fixture",
        "inputSchema": {
            "type": "object",
            "x-cua-step-only": True,
            "x-cua-mcp-binding": {
                "server_id": "server",
                "server_name": "fixture",
                "revision": 1,
                "catalog_digest": "digest",
            },
        },
        "annotations": {"readOnlyHint": True},
    }
    await bridge.devices.register(
        DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d"),
        "connection",
        [OUTER, mcp],
    )
    task = asyncio.create_task(
        bridge.request(authorization(agent_id="agent"), "cua_repl_js", {"code": CODE})
    )
    events = await bridge.redis.xread({control_key("connection"): "0-0"}, block=1000)
    request_id = events[0][1][-1][1]["request_id"]
    await bridge.claim(request_id, user_id="u", device_id="d")
    app, _, _ = application(bridge, monkeypatch)
    servers = AsyncMock(return_value=())
    monkeypatch.setattr(routes, "current_agent_servers", servers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        endpoint = f"/api/v1/agent/device/requests/{request_id}/steps/mcp/authorize"
        body = {
            **BODY,
            "tool_name": mcp["name"],
            "input_json": "{}",
            "target": {"kind": "mcp_tool", "id": "server/opaque"},
        }
        assert (await client.post(endpoint, json=body)).status_code == 409
        servers.return_value = ("server",)
        pending = await client.post(endpoint, json=body)
        assert pending.json()["status"] == "pending"
        servers.side_effect = [("server",), ()]
        assert (await client.post(endpoint, json=body)).status_code == 409
    await finish(bridge, request_id, task)


async def test_known_not_sent_release_rebases_current_revision_without_replaying_unknown(
    bridge, monkeypatch
):
    from src.tests.integration.agent.test_native_computer_claims import authority

    await register(bridge)
    task, request_id = await outer(bridge)
    run = authority()
    app, _, _ = application(bridge, monkeypatch, run=run)
    monkeypatch.setattr(routes, "current_agent_servers", AsyncMock(return_value=()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        endpoint = f"/api/v1/agent/device/requests/{request_id}/steps/read/authorize"
        body = {
            **BODY,
            "tool_name": READ["name"],
            "input_json": json.dumps({"operation": "playwright.domSnapshot"}),
        }
        ready = (await client.post(endpoint, json=body)).json()
        consumed = {**body, "receipt": ready["receipt"]}
        assert (await client.post(endpoint, json=consumed)).json()["status"] == "authorized"
        assert (
            await client.post(endpoint, json={**consumed, "outcome": "unknown"})
        ).status_code == 422
        release = await client.post(endpoint, json={**consumed, "outcome": "not_sent"})
        assert release.json()["status"] == "released"
        assert (await client.post(endpoint, json={**consumed, "outcome": "not_sent"})).json()[
            "status"
        ] == "released"
        await finish(bridge, request_id, task)
        run.revision = 2
        next_task, next_id = await outer(bridge, "resume", revision=2)
        endpoint = f"/api/v1/agent/device/requests/{next_id}/steps/read/authorize"
        body["parent_request_id"] = request_id
        ready = (await client.post(endpoint, json=body)).json()
        assert ready["status"] == "ready" and ready["authorization_revision"] == 2
        assert "continuation" not in ready
        assert ready["receipt"] != consumed["receipt"]
        assert (await client.post(endpoint, json={**body, "receipt": ready["receipt"]})).json()[
            "status"
        ] == "authorized"
        await finish(bridge, next_id, next_task)


async def test_live_http_receipt_consumption_and_known_not_sent_release(bridge, monkeypatch):
    import socket

    import uvicorn

    await register(bridge)
    task, request_id = await outer(bridge)
    app, _, _ = application(bridge, monkeypatch)
    monkeypatch.setattr(routes, "current_agent_servers", AsyncMock(return_value=()))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        address = listener.getsockname()[1]
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{address}") as client:
            endpoint = f"/api/v1/agent/device/requests/{request_id}/steps/live/authorize"
            body = {
                **BODY,
                "tool_name": READ["name"],
                "input_json": json.dumps({"operation": "playwright.domSnapshot"}),
            }
            wrong_owner = await client.post(endpoint, json={**body, "device_id": "foreign"})
            assert wrong_owner.status_code == 409
            ready = await client.post(endpoint, json=body)
            assert ready.status_code == 200, ready.text
            body["receipt"] = ready.json()["receipt"]
            consumed = await client.post(endpoint, json=body)
            assert consumed.json()["status"] == "authorized"
            assert (await client.post(endpoint, json=body)).status_code == 409
            released = await client.post(endpoint, json={**body, "outcome": "not_sent"})
            assert released.json()["status"] == "released"
            await bridge.cancel_request(request_id)
            assert (await client.post(endpoint, json=body)).status_code == 409
        await task
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 5)
        listener.close()


async def test_catalog_replaced_during_final_agent_check_cannot_issue_receipt(bridge, monkeypatch):
    await register(bridge)
    task, request_id = await outer(bridge)
    app, _, _ = application(bridge, monkeypatch)
    checks = 0

    async def agent_servers(*_args):
        nonlocal checks
        checks += 1
        if checks == 2:
            await bridge.devices.register(
                DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d"),
                "connection",
                [OUTER, INNER, {**READ, "description": "Replaced while authorizing"}],
            )
        return ()

    monkeypatch.setattr(routes, "current_agent_servers", agent_servers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/agent/device/requests/{request_id}/steps/race/authorize",
            json={**BODY, "tool_name": READ["name"], "input_json": '{"operation":"tab.url"}'},
        )
        assert response.status_code == 409
        parent = await bridge.read(request_key(request_id))
        assert await bridge.read(step_key(parent, "cell", "race")) is None
    await finish(bridge, request_id, task)


def test_cell_transport_timeout_covers_requested_runtime(bridge):
    assert bridge._request_timeout("cua_repl_js", {"timeout_ms": 300_000}) == 315
    assert bridge._request_timeout("computer_get_app_state", {}) == bridge.timeout


@pytest.mark.parametrize(
    ("operation", "args", "effect"),
    [
        ("browsers.resolve", [{"url": "https://example.test"}], "read"),
        ("capability.management.bookmarks.search", ["fixture"], "read"),
        ("capability.visibility.set", [True], "mutate"),
        ("capability.browserAuth.request", [], "mutate"),
        ("content.exportGsuite", [], "read"),
        ("playwright.waitForEvent", ["download"], "mutate"),
        ("playwright.waitForEvent", ["filechooser"], "mutate"),
    ],
)
def test_registered_browser_protocol_effects_match_dispatch(operation, args, effect):
    from src.infrastructure.agent.native_computer_use.catalog import browser_effect
    from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError

    tool = "browser_read_operation" if effect == "read" else "browser_write_operation"
    assert browser_effect(tool, {"operation": operation, "args": args}) == effect
    opposite = "browser_write_operation" if effect == "read" else "browser_read_operation"
    with pytest.raises(DeviceBridgeError):
        browser_effect(opposite, {"operation": operation, "args": args})
