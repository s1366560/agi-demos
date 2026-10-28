"""Ordinary selected-device MCP claims bind the live agent roster and catalog."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from src.infrastructure.adapters.primary.web.routers.agent import computer_use_steps
from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, control_key
from src.tests.integration.agent.test_native_computer_bridge import authorization, bridge as _bridge
from src.tests.integration.agent.test_native_computer_claims import application, authority

pytestmark = pytest.mark.integration
bridge = _bridge
BINDING = {
    "server_id": "owned",
    "server_name": "owned-server",
    "revision": 1,
    "catalog_digest": "one",
}
DEFINITION = {
    "name": "mcp_owned",
    "description": "Owned MCP operation",
    "inputSchema": {"type": "object", "x-cua-mcp-binding": BINDING},
}


@pytest.mark.parametrize("change", [None, "catalog", "roster", "roster_race", "visibility"])
async def test_outer_mcp_claim_checks_current_agent_and_exact_catalog(bridge, monkeypatch, change):
    scope = DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d")
    await bridge.devices.register(scope, "connection", [DEFINITION])
    auth = authorization(permission_profile="full_access", allowed_mcp_servers=("owned",))
    assert [
        tool["name"]
        for tool in await bridge.describe_tools(user_id="u", tenant_id="t", project_id="p")
    ] == ["mcp_owned"]
    task = asyncio.create_task(bridge.request(auth, "mcp_owned", {"value": "owned"}))
    messages = await bridge.redis.xread({control_key("connection"): "0-0"}, block=1000)
    request_id = messages[0][1][-1][1]["request_id"]
    app, _, _ = application(
        bridge,
        monkeypatch,
        run=authority(
            permission_profile="full_access",
            authorization_snapshot={
                "source": "chat_admission",
                "schema_version": 1,
                "effective_permission_mode": "full_access",
                "workspace_id": None,
            },
        ),
        policy={"permission_mode": "full_access"},
    )
    roster = AsyncMock(return_value=() if change == "roster" else ("owned",))
    if change == "roster_race":
        roster.side_effect = [("owned",), ()]
    monkeypatch.setattr(computer_use_steps, "current_agent_servers", roster)
    if change in {"catalog", "visibility"}:
        changed = deepcopy(DEFINITION)
        if change == "catalog":
            changed["inputSchema"]["x-cua-mcp-binding"]["catalog_digest"] = "two"
        else:
            changed["inputSchema"]["x-cua-step-only"] = True
        await bridge.devices.register(scope, "connection", [changed])
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/v1/agent/device/requests/{request_id}/claim", json={"device_id": "d"}
            )
            if change:
                assert response.status_code == 409, response.text
            else:
                assert response.status_code == 200, response.text
                assert response.json()["mcp_binding"] == BINDING
                assert response.json()["allowed_mcp_servers"] == ["owned"]
                assert roster.await_count == 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_app_only_mcp_is_inner_only_and_outer_requires_mutation_authority(bridge):
    scope = DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d")
    await bridge.devices.register(scope, "connection", [DEFINITION])
    with pytest.raises(DeviceBridgeError, match="permission_denied"):
        await bridge.request(authorization(allowed_mcp_servers=("owned",)), "mcp_owned", {})
    hidden = deepcopy(DEFINITION)
    hidden["inputSchema"]["x-cua-step-only"] = True
    await bridge.devices.register(scope, "connection", [hidden])
    assert not await bridge.describe_tools(user_id="u", tenant_id="t", project_id="p")
    with pytest.raises(DeviceBridgeError, match="step_context_required"):
        await bridge.request(
            authorization(permission_profile="full_access", allowed_mcp_servers=("owned",)),
            "mcp_owned",
            {},
        )
    assert await bridge.redis.xlen(control_key("connection")) == 0
