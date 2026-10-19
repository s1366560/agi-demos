"""Authenticated native control outcomes and durable, generation-bound wakeups."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from redis.asyncio.client import Pipeline

from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.devices import device_key
from src.infrastructure.agent.native_computer_use.store import (
    REQUEST_SECONDS,
    BridgeStore,
    DeviceBridgeError,
    identifier,
    request_key,
    string,
)
from src.infrastructure.agent.tools.result import ToolControlOutcome


def generation_id(value: object) -> str:
    text = identifier(value)
    try:
        if str(UUID(text)) != text:
            raise ValueError
    except ValueError as exc:
        raise DeviceBridgeError("computer_use_invalid_control_generation") from exc
    return text


def validate_control(message: dict[str, Any]) -> tuple[ToolControlOutcome | None, str | None]:
    """Only the independent transport discriminant conveys native provenance."""
    outcome = message.get("control_outcome")
    generation = message.get("control_generation")
    if outcome is None:
        if generation is not None:
            raise DeviceBridgeError("computer_use_invalid_control_result")
        return None, None
    try:
        control = ToolControlOutcome(outcome)
        payload = json.loads(message["output_json"])
    except (ValueError, TypeError, KeyError) as exc:
        raise DeviceBridgeError("computer_use_invalid_control_result") from exc
    if (
        message.get("is_error") is not False
        or message.get("media") != []
        or payload
        != {"type": "computer_use_control", "status": control.value, "retry_allowed": False}
        or payload.get("retry_allowed") is not False
    ):
        raise DeviceBridgeError("computer_use_invalid_control_result")
    if control == ToolControlOutcome.USER_PAUSED:
        return control, generation_id(generation)
    if generation is not None:
        raise DeviceBridgeError("computer_use_invalid_control_result")
    return control, None


def wake_key(request_id: str) -> str:
    return f"{request_key(request_id)}:native-control"


class ControlTransport(BridgeStore):
    async def require_live_control_device(self, value: dict[str, Any]) -> None:
        scope = DeviceScope(
            **{key: value[key] for key in ("user_id", "tenant_id", "project_id", "device_id")}
        )
        device = await self.read(device_key(scope))
        if (
            device is None
            or device.get("connection_id") != value["connection_id"]
            or not any(
                item.get("name") == value["tool_name"]
                for item in device.get("tool_definitions", [])
            )
        ):
            raise DeviceBridgeError("computer_use_device_disconnected")

    async def receive_control_state(self, connection_id: str, message: dict[str, Any]) -> None:
        request_id = identifier(message.get("request_id"))
        session_id = identifier(message.get("session_id"))
        generation = generation_id(message.get("control_generation"))
        state = message.get("state")
        if state not in ("resumed", "stopped"):
            raise DeviceBridgeError("computer_use_invalid_control_state")
        initial = await self.read(request_key(request_id))
        if initial is None or initial.get("connection_id") != connection_id:
            raise DeviceBridgeError("computer_use_control_access_denied")
        await self.require_live_control_device(initial)

        def change(value: dict[str, Any] | None) -> dict[str, Any]:
            if (
                value is None
                or value.get("connection_id") != connection_id
                or value.get("session_id") != session_id
                or value.get("cancelled")
                or value.get("status") not in ("claimed", "completed")
            ):
                raise DeviceBridgeError("computer_use_control_access_denied")
            if value["status"] == "completed" and (
                value.get("control_outcome") != "user_paused"
                or value.get("control_generation") != generation
            ):
                raise DeviceBridgeError("computer_use_control_generation_mismatch")
            # Before the tool result arrives this is only an untrusted candidate.
            # The waiter validates it against the eventual signed native result.
            candidate = value.get("control_notification")
            current = {"generation": generation, "state": state}
            if (
                value["status"] == "completed"
                and candidate is not None
                and candidate.get("generation") == generation
                and candidate != current
            ):
                # A Stop may supersede Resume for this same pause episode.
                if (
                    candidate != {"generation": generation, "state": "resumed"}
                    or state != "stopped"
                ):
                    raise DeviceBridgeError("computer_use_control_already_settled")
            return {**value, "control_notification": current}

        def extra(pipe: Pipeline, _value: dict[str, Any]) -> None:
            pipe.xadd(wake_key(request_id), {"generation": generation, "state": state}, maxlen=8)
            pipe.expire(wake_key(request_id), REQUEST_SECONDS)

        await self.update(request_key(request_id), change, extra=extra)

    @staticmethod
    def control_cancel_event(pipe: Pipeline, value: dict[str, Any]) -> None:
        key = wake_key(value["request_id"])
        pipe.xadd(key, {"state": "cancelled"}, maxlen=8)
        pipe.expire(key, REQUEST_SECONDS)

    async def wait_control(self, request_id: str, generation: str) -> ToolControlOutcome | None:
        """Never dispatch tools here; Resume only releases the next model boundary."""
        cursor = "0-0"
        while True:
            value = await self.read(request_key(request_id))
            if value is None or value.get("cancelled"):
                raise DeviceBridgeError("computer_use_control_cancelled")
            await self.require_live_control_device(value)
            if (
                value.get("control_outcome") != "user_paused"
                or value.get("control_generation") != generation
            ):
                raise DeviceBridgeError("computer_use_control_generation_mismatch")
            notification = value.get("control_notification")
            if notification and notification.get("generation") == generation:
                return (
                    ToolControlOutcome.USER_STOPPED if notification["state"] == "stopped" else None
                )
            # Redis blocks without polling the device or retrying the original tool.
            batches = await self.redis.xread({wake_key(request_id): cursor}, count=8, block=30_000)
            for _stream, events in batches:
                for event_id, _fields in events:
                    cursor = string(event_id)
