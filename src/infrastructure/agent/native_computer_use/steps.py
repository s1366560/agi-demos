"""Persistent, exact-input one-shot receipts for operations inside a REPL cell."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from typing import Any

from src.infrastructure.agent.native_computer_use.catalog import EXECUTE_TOOLS
from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.devices import device_key
from src.infrastructure.agent.native_computer_use.store import (
    REQUEST_SECONDS,
    BridgeStore,
    DeviceBridgeError,
    digest,
    encoded,
    identifier,
    request_key,
)

SCOPE_FIELDS = (
    "user_id",
    "tenant_id",
    "project_id",
    "conversation_id",
    "run_id",
    "session_id",
    "device_id",
    "connection_id",
    "agent_id",
    "child_run_id",
    "child_owner_digest",
)


def step_key(parent: dict[str, Any], cell_id: str, step_id: str) -> str:
    return f"{request_key(parent['request_id'])}:step:{digest([cell_id, step_id])}"


def code_digest(parent: dict[str, Any]) -> str:
    if parent["tool_name"] != "cua_repl_js":
        raise DeviceBridgeError("computer_use_step_parent_invalid")
    value = json.loads(parent["input_json"])
    if not isinstance(value.get("code"), str) or not value["code"]:
        raise DeviceBridgeError("computer_use_step_parent_invalid")
    return hashlib.sha256(value["code"].encode()).hexdigest()


class ExecutionSteps(BridgeStore):
    async def authorize(
        self,
        parent: dict[str, Any],
        step_id: str,
        body: dict[str, Any],
        *,
        effect: str,
        catalog_digest: str,
    ) -> dict[str, Any]:
        """Issue or consume a receipt; never execute the operation here."""
        if body["tool_name"] in EXECUTE_TOOLS:
            raise DeviceBridgeError("computer_use_recursive_step_denied")
        cell_id = identifier(body["cell_id"])
        identifier(step_id)
        origin_id = body.get("parent_request_id") or parent["request_id"]
        origin = await self.read(request_key(origin_id))
        if origin is None or any(origin.get(k) != parent.get(k) for k in SCOPE_FIELDS):
            raise DeviceBridgeError("computer_use_step_parent_changed")
        if code_digest(origin) != code_digest(parent):
            raise DeviceBridgeError("computer_use_step_code_changed")
        if origin_id != parent["request_id"] and (
            origin.get("cancelled") or origin.get("status") != "completed"
        ):
            raise DeviceBridgeError("computer_use_step_parent_invalid")
        key = step_key(origin, cell_id, step_id)
        binding = {
            "cell_id": cell_id,
            "step_id": step_id,
            "tool_name": body["tool_name"],
            "input_digest": hashlib.sha256(body["input_json"].encode()).hexdigest(),
            "target": body["target"],
            "code_digest": code_digest(parent),
            "catalog_digest": catalog_digest,
            "effect": effect,
            **{name: parent.get(name) for name in SCOPE_FIELDS},
        }
        from src.infrastructure.agent.native_computer_use.permission_result import input_digest

        try:
            permission_digest = input_digest(body["input_json"])
        except DeviceBridgeError:
            # A successful operation retains its original receipt protocol. Inputs outside
            # JCS cannot acquire permission provenance, but are still ordinary tool data.
            permission_digest = None
        previous = await self.read(key)
        if previous is None and origin_id != parent["request_id"]:
            raise DeviceBridgeError("computer_use_step_resume_missing")

        def change(current: dict[str, Any] | None) -> dict[str, Any]:
            result = _next_state(
                current, binding, parent, origin_id, key, body.get("receipt"), body.get("outcome")
            )
            return {**result, "permission_input_digest": permission_digest}

        value = await self._update_live(key, parent, body["tool_name"], catalog_digest, change)
        if value["status"] == "pending":
            return {
                "status": "pending",
                "error": "cua_permission_required",
                "scopes": ["once"],
                "request": self.pending(value),
            }
        result = {
            "status": "authorized" if value["status"] == "consumed" else value["status"],
            "receipt": value["receipt"],
            "step_id": step_id,
            "cell_id": cell_id,
            "input_digest": value["input_digest"],
            "catalog_digest": catalog_digest,
            "authorization_revision": value["authorization_revision"],
        }
        if value.get("continuation") is not None:
            result["continuation"] = value["continuation"]
        return result

    async def _update_live(
        self,
        key: str,
        parent: dict[str, Any],
        tool_name: str,
        catalog_digest: str,
        change: Callable[[dict[str, Any] | None], dict[str, Any]],
    ) -> dict[str, Any]:
        """Watch the parent claim as well as the step so cancel wins a race."""
        from redis.exceptions import WatchError

        from src.infrastructure.agent.native_computer_use.store import record

        for _attempt in range(8):
            async with self.redis.pipeline(transaction=True) as pipe:
                try:
                    parent_key = request_key(parent["request_id"])
                    registry_key = device_key(
                        DeviceScope(
                            **{
                                name: parent[name]
                                for name in ("user_id", "tenant_id", "project_id", "device_id")
                            }
                        )
                    )
                    await pipe.watch(key, parent_key, registry_key)
                    device = record(await pipe.get(registry_key))
                    definition = next(
                        (
                            tool
                            for tool in (device or {}).get("tool_definitions", [])
                            if tool.get("name") == tool_name
                        ),
                        None,
                    )
                    if (
                        device is None
                        or device.get("connection_id") != parent["connection_id"]
                        or definition is None
                        or digest(definition) != catalog_digest
                    ):
                        raise DeviceBridgeError("computer_use_catalog_changed")
                    live = record(await pipe.get(parent_key))
                    if (
                        live is None
                        or live.get("status") != "claimed"
                        or live.get("cancelled")
                        or live["expires_at"] <= time.time()
                    ):
                        raise DeviceBridgeError("computer_use_step_parent_inactive")
                    if any(
                        live.get(k) != parent.get(k)
                        for k in (*SCOPE_FIELDS, "authorization_revision")
                    ):
                        raise DeviceBridgeError("computer_use_step_parent_changed")
                    result = change(record(await pipe.get(key)))
                    begin_transaction: Callable[[], None] = pipe.multi
                    begin_transaction()
                    pipe.set(key, encoded(result), ex=REQUEST_SECONDS)
                    pipe.sadd(f"{parent_key}:steps", key)
                    pipe.expire(f"{parent_key}:steps", REQUEST_SECONDS)
                    await pipe.execute()
                    return result
                except WatchError:
                    continue
        raise DeviceBridgeError("computer_use_concurrent_update")

    @staticmethod
    def pending(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": value["permission_id"],
            "session_id": value["cell_id"],
            "engine_session_id": value["session_id"],
            "app": value["target"]["id"],
            "identity_digest": value["catalog_digest"],
            "capability": "execution_step",
            "tool_name": value["tool_name"],
            "input_digest": value["input_digest"],
            "execution_step": {
                "key": value["step_key"],
                "cell_id": value["cell_id"],
                "step_id": value["step_id"],
                "target": value["target"],
                "code_digest": value["code_digest"],
            },
        }

    async def resolve_permission(
        self, binding: dict[str, Any], granted: bool, *, hitl_request_id: str
    ) -> None:
        """Called only after the bound HITL response commits, never by a device claim."""
        identifier(hitl_request_id)
        step = binding["execution_step"]

        def change(value: dict[str, Any] | None) -> dict[str, Any]:
            if (
                value is None
                or value["status"] != "pending"
                or any(
                    value.get(k) != binding.get(k)
                    for k in (
                        "user_id",
                        "tenant_id",
                        "project_id",
                        "conversation_id",
                        "run_id",
                        "session_id",
                        "device_id",
                        "tool_name",
                        "input_digest",
                    )
                )
                or value["permission_id"] != binding["native_request_id"]
                or type(binding.get("authorization_revision")) is not int
                or binding["authorization_revision"] < value["authorization_revision"]
            ):
                raise DeviceBridgeError("computer_use_step_permission_changed")
            resolved = {
                **value,
                "status": "approved" if granted else "denied",
                "authorization_revision": binding["authorization_revision"],
            }
            if granted:
                resolved["continuation"] = {
                    "kind": "hitl",
                    "hitl_request_id": hitl_request_id,
                    "origin_request_id": value["origin_request_id"],
                    "previous_authorization_revision": value["authorization_revision"],
                    "authorization_revision": binding["authorization_revision"],
                    "cell_id": value["cell_id"],
                    "step_id": value["step_id"],
                }
            return resolved

        await self.update(step["key"], change)


def _next_state(
    current: dict[str, Any] | None,
    binding: dict[str, Any],
    parent: dict[str, Any],
    origin_id: str,
    key: str,
    receipt: str | None,
    outcome: str | None = None,
) -> dict[str, Any]:
    if current is None:
        pending = binding["effect"] != "read" and parent["permission_profile"] != "full_access"
        current = {
            **binding,
            "status": "pending" if pending else "approved",
            "authorization_revision": parent["authorization_revision"],
            "origin_request_id": origin_id,
            "current_request_id": parent["request_id"],
            "permission_id": secrets.token_hex(24),
            "step_key": key,
        }
    elif any(current.get(k) != v for k, v in binding.items()):
        raise DeviceBridgeError("computer_use_step_identity_changed")
    if outcome is not None:
        return _release(current, parent, receipt, outcome)
    if current["status"] == "released" and receipt is None:
        current = {
            **current,
            "status": "approved",
            "authorization_revision": parent["authorization_revision"],
        }
    if current["authorization_revision"] != parent["authorization_revision"]:
        raise DeviceBridgeError("computer_use_step_authority_changed")
    if current["status"] in {"consumed", "denied"}:
        raise DeviceBridgeError("computer_use_step_already_consumed")
    if receipt is not None:
        if current["status"] != "ready" or not secrets.compare_digest(current["receipt"], receipt):
            raise DeviceBridgeError("computer_use_step_receipt_invalid")
        if current["current_request_id"] != parent["request_id"]:
            raise DeviceBridgeError("computer_use_step_receipt_parent_changed")
        return {**current, "status": "consumed", "consumed_at": time.time()}
    if current["status"] == "approved":
        return {
            **current,
            "status": "ready",
            "receipt": secrets.token_urlsafe(32),
            "current_request_id": parent["request_id"],
        }
    if current["status"] == "ready" and current["current_request_id"] != parent["request_id"]:
        raise DeviceBridgeError("computer_use_step_receipt_parent_changed")
    return current


def _release(
    current: dict[str, Any], parent: dict[str, Any], receipt: str | None, outcome: str
) -> dict[str, Any]:
    if (
        outcome != "not_sent"
        or current["status"] not in {"consumed", "released"}
        or not receipt
        or not secrets.compare_digest(current["receipt"], receipt)
        or current["current_request_id"] != parent["request_id"]
    ):
        raise DeviceBridgeError("computer_use_step_release_invalid")
    released = {**current, "status": "released", "last_outcome": "not_sent"}
    released.pop("continuation", None)
    return released
