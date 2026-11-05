"""Bounded run continuity; this never authorizes another tool invocation."""

from __future__ import annotations

import json
from typing import Any

from src.infrastructure.agent.native_computer_use.permission_result import input_digest
from src.infrastructure.agent.native_computer_use.steps import SCOPE_FIELDS, step_key
from src.infrastructure.agent.native_computer_use.store import (
    BridgeStore,
    DeviceBridgeError,
    request_key,
)


def require_source(
    value: dict[str, Any] | None, *, user_id: str, device_id: str, session_id: str
) -> dict[str, Any]:
    if (
        value is None
        or value.get("user_id") != user_id
        or value.get("device_id") != device_id
        or value.get("session_id") != session_id
        or value.get("status") not in {"claimed", "receiving", "completed"}
        or value.get("cancelled") is True
        or value.get("is_error") is True
        or value.get("permission_required") is not None
        or value.get("control_outcome") is not None
    ):
        raise DeviceBridgeError("computer_use_continuity_unavailable")
    return value


async def require_enable(
    store: BridgeStore,
    source: dict[str, Any],
    *,
    cell_id: str | None,
    step_id: str | None,
    parent_request_id: str | None,
) -> None:
    if source["tool_name"] == "computer_locked_use":
        if any(value is not None for value in (cell_id, step_id, parent_request_id)):
            raise DeviceBridgeError("computer_use_continuity_step_invalid")
        try:
            arguments = json.loads(source["input_json"])
        except (TypeError, ValueError) as exc:
            raise DeviceBridgeError("computer_use_continuity_step_invalid") from exc
        if arguments != {"enabled": True} or arguments.get("enabled") is not True:
            raise DeviceBridgeError("computer_use_continuity_enable_required")
        return
    if source["tool_name"] != "cua_repl_js" or not cell_id or not step_id:
        raise DeviceBridgeError("computer_use_continuity_enable_required")
    origin = await store.read(request_key(parent_request_id or source["request_id"]))
    if origin is None or any(origin.get(key) != source.get(key) for key in SCOPE_FIELDS):
        raise DeviceBridgeError("computer_use_continuity_origin_changed")
    step = await store.read(step_key(origin, cell_id, step_id))
    if (
        step is None
        or step.get("status") != "consumed"
        or step.get("current_request_id") != source["request_id"]
        or step.get("authorization_revision") != source["authorization_revision"]
        or step.get("tool_name") != "computer_locked_use"
        or step.get("permission_input_digest") != input_digest('{"enabled":true}')
        or any(step.get(key) != source.get(key) for key in SCOPE_FIELDS)
    ):
        raise DeviceBridgeError("computer_use_continuity_enable_required")
