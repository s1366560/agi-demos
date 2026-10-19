"""Closed connector operation effects declared by an authenticated device."""

from __future__ import annotations

import json
from typing import Any, Literal

from jsonschema import Draft202012Validator

from src.infrastructure.agent.native_computer_use.contracts import READ_TOOL_NAMES
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError

OPERATION_EFFECTS = "x-cua-operation-effects"
Effect = Literal["read", "mutate"]
# These are protocol operations, never a classification of user text or intent.
NATIVE_OPERATIONS = {
    ("calendar", "list"): "read",
    ("calendar", "create"): "mutate",
    ("calendar", "update"): "mutate",
    ("calendar", "delete"): "mutate",
    ("contacts", "list"): "read",
    ("contacts", "create"): "mutate",
    ("contacts", "update"): "mutate",
    ("contacts", "delete"): "mutate",
    ("messages", "list"): "read",
    ("messages", "services"): "read",
    ("messages", "resolve_recipient"): "read",
    ("messages", "send"): "mutate",
}
_ROW_VALIDATOR = Draft202012Validator(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["provider", "connector", "operation", "effect"],
        "properties": {
            "provider": {"enum": ["native", "google", "microsoft365", "configured_mcp"]},
            "connector": {"enum": ["calendar", "contacts", "messages"]},
            "effect": {"enum": ["read", "mutate"]},
            "operation": {"type": "string", "minLength": 1, "maxLength": 256},
            "account_id": {"type": ["string", "null"], "minLength": 1, "maxLength": 256},
            "server_id": {"type": ["string", "null"], "minLength": 1, "maxLength": 256},
            "server_name": {"type": ["string", "null"], "minLength": 1, "maxLength": 256},
            "managed_account": {"type": "boolean"},
        },
    }
)


def operation_rows(schema: dict[str, Any]) -> list[dict[str, Any]]:
    rows = schema.get(OPERATION_EFFECTS, [])
    if not isinstance(rows, list) or len(rows) > 512:
        raise DeviceBridgeError("cua_connector_effects_invalid")
    seen: set[tuple[str, str | None, str, str]] = set()
    for row in rows:
        if not _ROW_VALIDATOR.is_valid(row):
            raise DeviceBridgeError("cua_connector_effects_invalid")
        provider, account = row.get("provider"), row.get("account_id")
        connector, operation, effect = row.get("connector"), row.get("operation"), row.get("effect")
        if (
            any(
                isinstance(row.get(key), str) and len(row[key].encode()) > 256
                for key in ("operation", "account_id", "server_id", "server_name")
            )
            or (provider != "native" and account is None)
            or (
                provider == "native"
                and (account is not None or NATIVE_OPERATIONS.get((connector, operation)) != effect)
            )
            or (row.get("managed_account") is True and provider not in {"google", "microsoft365"})
            or (
                provider == "native"
                and any(row.get(key) is not None for key in ("server_id", "server_name"))
            )
        ):
            raise DeviceBridgeError("cua_connector_effects_invalid")
        key = (provider, account, connector, operation)
        if key in seen:
            raise DeviceBridgeError("cua_connector_effects_invalid")
        seen.add(key)
    return rows


def argument_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Custom metadata does not become a model-supplied JSON Schema property."""
    operation_rows(schema)
    return {key: value for key, value in schema.items() if key != OPERATION_EFFECTS}


def tool_effect(tool_name: str, schema: dict[str, Any], arguments: dict[str, Any]) -> Effect:
    if tool_name in READ_TOOL_NAMES:
        return "read"
    if tool_name != "computer_connector_call":
        return "mutate"
    candidates = matching_rows(schema, arguments)
    return "read" if candidates and all(row["effect"] == "read" for row in candidates) else "mutate"


def matching_rows(schema: dict[str, Any], arguments: dict[str, Any]) -> list[dict[str, Any]]:
    provider = arguments.get("provider", "native")
    return [
        row
        for row in operation_rows(schema)
        if row["connector"] == arguments.get("connector")
        and row["operation"] == arguments.get("operation")
        and (
            row["provider"] == provider
            or (provider == "configured_mcp" and row["provider"] != "native")
        )
        and (
            row["provider"] == "native"
            or arguments.get("account_id") in (None, row.get("account_id"))
        )
    ]


def require_connector_servers(
    schema: dict[str, Any], arguments: dict[str, Any], allowed: tuple[str, ...]
) -> None:
    if arguments.get("provider", "native") == "native":
        return
    candidates = matching_rows(schema, arguments)
    if not candidates or not all(
        (row.get("managed_account") is True and row["provider"] in {"google", "microsoft365"})
        or (
            any(isinstance(row.get(key), str) for key in ("server_id", "server_name"))
            and (
                "*" in allowed
                or row.get("server_id") in allowed
                or row.get("server_name") in allowed
            )
        )
        for row in candidates
    ):
        raise DeviceBridgeError("computer_use_mcp_server_denied")


def device_effect(device: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> Effect:
    for definition in device.get("tool_definitions", []):
        if definition.get("name") == tool_name:
            return tool_effect(tool_name, definition["inputSchema"], arguments)
    return "mutate"


def selection_effect(
    devices: list[dict[str, Any]], tool_name: str, arguments: dict[str, Any]
) -> Effect:
    selected = [
        device for device in devices if arguments.get("device_id") in (None, device["device_id"])
    ]
    return (
        "read"
        if selected
        and all(device_effect(device, tool_name, arguments) == "read" for device in selected)
        else "mutate"
    )


def validate_registered_call(device: dict[str, Any], value: dict[str, Any]) -> Effect:
    """Recheck the current catalog before consuming a queued device invocation."""
    from src.infrastructure.agent.native_computer_use.schema import validator

    definition = next(
        (item for item in device["tool_definitions"] if item.get("name") == value["tool_name"]),
        None,
    )
    if definition is None:
        raise DeviceBridgeError("computer_use_tool_unavailable")
    try:
        arguments = json.loads(value["input_json"])
    except (ValueError, TypeError) as error:
        raise DeviceBridgeError("computer_use_invalid_params") from error
    schema = definition["inputSchema"]
    if not isinstance(arguments, dict) or not validator(argument_schema(schema)).is_valid(
        arguments
    ):
        raise DeviceBridgeError("computer_use_invalid_params")
    effect = tool_effect(value["tool_name"], schema, arguments)
    if value.get("tool_effect", effect) != effect:
        raise DeviceBridgeError("computer_use_tool_effect_changed")
    if (
        effect != "read"
        and value["permission_profile"] != "full_access"
        and value["tool_name"] not in value["approved_tools"]
    ):
        raise DeviceBridgeError("computer_use_run_permission_denied")
    if value["tool_name"] == "computer_connector_call":
        require_connector_servers(schema, arguments, tuple(value.get("allowed_mcp_servers", ())))
    return effect
