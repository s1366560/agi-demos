"""Exact device operation metadata, current claims, and agent MCP ceilings."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.devices import DeviceRegistry
from src.infrastructure.agent.native_computer_use.effects import (
    OPERATION_EFFECTS,
    argument_schema,
    operation_rows,
    require_connector_servers,
    selection_effect,
    tool_effect,
    validate_registered_call,
)
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError
from src.infrastructure.agent.tools import native_computer_use as native
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.integration.agent.test_native_computer_bridge import authorization
from src.tests.unit.infrastructure.agent.test_native_computer_use import context, setup_guard

pytestmark = pytest.mark.unit
NAME = "computer_connector_call"


def definition(*rows):
    return {
        "name": NAME,
        "description": "Explicit connector operations",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "provider": {"enum": ["native", "google", "microsoft365", "configured_mcp"]},
                "account_id": {"type": "string"},
                "connector": {"enum": ["calendar", "contacts", "messages"]},
                "operation": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["connector", "operation", "arguments"],
            OPERATION_EFFECTS: list(rows),
        },
    }


def row(**changes):
    return {
        "provider": "native",
        "connector": "calendar",
        "operation": "list",
        "effect": "read",
        **changes,
    }


def device(*rows, device_id="d"):
    return {
        "device_id": device_id,
        "connection_id": "connection",
        "tool_definitions": [definition(*rows)],
    }


def arguments(**changes):
    return {"connector": "calendar", "operation": "list", "arguments": {}, **changes}


@pytest.mark.parametrize("connector", ["calendar", "contacts", "messages"])
def test_declared_native_queries_are_read_and_same_name_elsewhere_is_mutating(connector):
    schema = definition(row(connector=connector))["inputSchema"]
    assert tool_effect(NAME, schema, arguments(connector=connector)) == "read"
    assert tool_effect(NAME, schema, arguments(connector=connector, provider="google")) == "mutate"
    assert (
        tool_effect(NAME, schema, arguments(connector=connector, operation="list_everything"))
        == "mutate"
    )
    assert OPERATION_EFFECTS not in argument_schema(schema)


@pytest.mark.parametrize(
    "invalid",
    [
        "not-a-list",
        [42],
        [row(effect="probably-safe")],
        [row(effect="mutate")],
        [row(operation="create")],
        [row(), row()],
        [row(extra="model-effect")],
        [row(provider=["native"])],
        [row(provider="google")],
        [row(managed_account=True)],
        [row(provider="configured_mcp", account_id="a", managed_account=True)],
        [row(operation="中" * 100)],
        [row()] * 513,
    ],
)
def test_invalid_duplicate_or_forged_static_metadata_is_rejected(invalid):
    with pytest.raises(DeviceBridgeError, match="effects_invalid"):
        operation_rows({OPERATION_EFFECTS: invalid})


def test_exact_account_and_multidevice_permission_is_conservative():
    read = row(provider="google", account_id="a", operation="opaque.17", managed_account=True)
    mutate = {**read, "account_id": "b", "effect": "mutate"}
    schema = definition(read, mutate)["inputSchema"]
    assert (
        tool_effect(
            NAME, schema, arguments(provider="google", account_id="a", operation="opaque.17")
        )
        == "read"
    )
    assert (
        tool_effect(
            NAME, schema, arguments(provider="google", account_id="b", operation="opaque.17")
        )
        == "mutate"
    )
    assert (
        tool_effect(NAME, schema, arguments(provider="configured_mcp", operation="opaque.17"))
        == "mutate"
    )
    assert (
        selection_effect([device(row()), device(device_id="other")], NAME, arguments()) == "mutate"
    )
    assert (
        selection_effect([device(row()), device(device_id="other")], NAME, arguments(device_id="d"))
        == "read"
    )
    assert selection_effect([device(row())], NAME, arguments(device_id="unknown")) == "mutate"


@pytest.mark.parametrize("allowed", [("server-id",), ("Calendar Backend",), ("*",)])
def test_external_server_is_bound_to_actual_configuration_not_account_name(allowed):
    external = row(
        provider="configured_mcp",
        account_id="opaque-account",
        server_id="server-id",
        server_name="Calendar Backend",
    )
    schema = definition(external)["inputSchema"]
    inputs = arguments(provider="configured_mcp", account_id="opaque-account")
    require_connector_servers(schema, inputs, allowed)
    with pytest.raises(DeviceBridgeError, match="mcp_server_denied"):
        require_connector_servers(schema, inputs, ("opaque-account",))
    with pytest.raises(DeviceBridgeError, match="mcp_server_denied"):
        require_connector_servers(
            definition(row(provider="google", account_id="a"))["inputSchema"],
            arguments(provider="google"),
            ("*",),
        )
    require_connector_servers(
        definition(row(provider="google", account_id="a", managed_account=True))["inputSchema"],
        arguments(provider="google", account_id="a"),
        (),
    )


def test_read_only_payload_allows_query_rejects_write_and_model_forged_effect():
    broker = NativeComputerBroker.__new__(NativeComputerBroker)
    broker.timeout = 3
    selected = device(row(), row(operation="create", effect="mutate"))
    payload = broker._payload(authorization(), NAME, arguments(), selected)
    assert payload["tool_effect"] == "read"
    assert validate_registered_call(selected, payload) == "read"
    for inputs in (arguments(operation="create"), arguments(operation="unknown")):
        with pytest.raises(DeviceBridgeError, match="permission_denied"):
            broker._payload(authorization(), NAME, inputs, selected)
    with pytest.raises(DeviceBridgeError, match="invalid_params"):
        broker._payload(authorization(), NAME, arguments(effect="read"), selected)
    changed = deepcopy(selected)
    changed["tool_definitions"][0]["inputSchema"][OPERATION_EFFECTS] = []
    with pytest.raises(DeviceBridgeError, match="effect_changed"):
        validate_registered_call(changed, payload)
    payload["input_json"] = json.dumps(arguments(operation="create"))
    payload.pop("tool_effect")
    with pytest.raises(DeviceBridgeError, match="permission_denied"):
        validate_registered_call(selected, payload)


async def test_actual_proxy_resolver_and_fresh_execution_recheck_device_roster(monkeypatch):
    catalog = [device(row())]
    broker = SimpleNamespace(
        describe_tools=AsyncMock(return_value=[definition(row())]),
        devices=SimpleNamespace(list=AsyncMock(side_effect=lambda **_scope: deepcopy(catalog))),
    )
    tools = await native.create_native_computer_tools(
        user_id="user", tenant_id="tenant", project_id="project", broker=broker
    )
    proxy = tools[NAME]
    assert proxy.permission_resolver(arguments()) == "read"
    assert proxy.permission_resolver(arguments(operation="create")) == "mcp"
    guard = setup_guard(monkeypatch)
    decision = AsyncMock(return_value="allow")
    monkeypatch.setattr(type(guard), "decision", decision)
    ctx = context()
    ctx.runtime_context["allowed_mcp_servers"] = ["actual-server"]
    sealed = await native.authorize_native_call(ctx, NAME, arguments(), broker=broker)
    decision.assert_awaited_once_with("read", NAME, arguments())
    assert sealed.allowed_mcp_servers == ("actual-server",)
    catalog.clear()
    decision.reset_mock()
    decision.return_value = "ask"
    with pytest.raises(RuntimeV2Error, match="approval"):
        await native.authorize_native_call(ctx, NAME, arguments(), broker=broker)
    decision.assert_awaited_once_with("mcp", NAME, arguments())


async def test_registration_rejects_invalid_effect_before_touching_private_store():
    registry = DeviceRegistry(object())
    registry.update = AsyncMock()
    with pytest.raises(DeviceBridgeError, match="effects_invalid"):
        await registry.register(
            DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d"),
            "connection",
            [definition(row(effect="mutate"))],
        )
    registry.update.assert_not_awaited()


async def test_model_catalog_keeps_common_schema_without_merging_permission_rows():
    broker = NativeComputerBroker.__new__(NativeComputerBroker)
    broker.devices = SimpleNamespace(
        list=AsyncMock(return_value=[device(row()), device(device_id="other")])
    )
    definitions = await broker.describe_tools(user_id="u", tenant_id="t", project_id="p")
    assert len(definitions) == 1
    assert OPERATION_EFFECTS not in definitions[0]["inputSchema"]
    assert broker.devices.list.call_args.kwargs == {
        "user_id": "u",
        "tenant_id": "t",
        "project_id": "p",
    }
