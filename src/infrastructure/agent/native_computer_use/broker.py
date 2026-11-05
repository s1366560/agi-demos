"""Cloud workers dispatch once to an authenticated, user-controlled device."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis

from src.infrastructure.agent.native_computer_use.contracts import CallAuthorization
from src.infrastructure.agent.native_computer_use.devices import DeviceRegistry
from src.infrastructure.agent.native_computer_use.effects import (
    argument_schema,
    require_connector_servers,
    tool_effect,
)
from src.infrastructure.agent.native_computer_use.media import MediaTransport
from src.infrastructure.agent.native_computer_use.schema import validator
from src.infrastructure.agent.native_computer_use.store import (
    REQUEST_SECONDS,
    DeviceBridgeError,
    control_key,
    conversation_key,
    digest,
    encoded,
    identifier,
    request_key,
    run_key,
    string,
)
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from redis.typing import EncodableT, FieldT


class NativeComputerBroker(MediaTransport):
    def __init__(self, redis: Redis, *, timeout: float = 120) -> None:
        super().__init__(redis)
        self.devices = DeviceRegistry(redis)
        self.timeout = timeout

    async def describe_tools(
        self, *, tenant_id: str, project_id: str, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        if user_id is None:
            return []
        devices = await self.devices.list(
            user_id=user_id, tenant_id=tenant_id, project_id=project_id
        )
        definitions: dict[str, dict[str, Any]] = {}
        conflicts: set[str] = set()
        for device in devices:
            for definition in device["tool_definitions"]:
                if definition["inputSchema"].get("x-cua-step-only") is True:
                    continue
                name = definition["name"]
                without_effects = {
                    **definition,
                    "inputSchema": argument_schema(definition["inputSchema"]),
                }
                if name in definitions and definitions[name] != without_effects:
                    conflicts.add(name)
                definitions[name] = without_effects
        return [definition for name, definition in definitions.items() if name not in conflicts]

    async def request(
        self, authorization: CallAuthorization, tool_name: str, arguments: dict[str, Any]
    ) -> ToolResult:
        self._validate_authorization(authorization, tool_name, check_effect=False)
        devices = await self._eligible_devices(authorization)
        if len(devices) != 1:
            return ToolResult(
                output=encoded(
                    {
                        "error": "device_selection_required",
                        "devices": [d["device_id"] for d in devices],
                    }
                ),
                is_error=True,
            )
        payload = self._payload(authorization, tool_name, arguments, devices[0])
        request_id = payload["request_id"]
        key = request_key(request_id)
        if await self.read(key) is not None:
            return await self._previous_result(key, payload)
        created = await self.redis.set(key, encoded(payload), nx=True, ex=REQUEST_SECONDS)
        if not created:
            return await self._previous_result(key, payload)
        index = run_key(
            authorization.user_id,
            authorization.tenant_id,
            authorization.project_id,
            authorization.run_id,
        )
        connection_index = f"{control_key(payload['connection_id'])}:requests"
        conversation_index = conversation_key(
            authorization.user_id,
            authorization.tenant_id,
            authorization.project_id,
            authorization.conversation_id,
        )
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.sadd(index, request_id)
            pipe.expire(index, REQUEST_SECONDS)
            pipe.sadd(connection_index, request_id)
            pipe.expire(connection_index, REQUEST_SECONDS)
            pipe.sadd(conversation_index, request_id)
            pipe.expire(conversation_index, REQUEST_SECONDS)
            await pipe.execute()
        try:
            await self.dispatch(
                payload["connection_id"],
                "computer_use_request",
                request_id,
                expires_at=payload["expires_at"],
            )
            return await self._wait_result(request_id, payload["expires_at"])
        except asyncio.CancelledError:
            await asyncio.shield(self.cancel_request(request_id))
            raise
        except Exception:
            await self.cancel_request(request_id)
            raise

    @staticmethod
    def _validate_authorization(
        authorization: CallAuthorization,
        tool_name: str,
        *,
        check_effect: bool = True,
        effect: str = "mutate",
    ) -> None:
        from src.infrastructure.agent.native_computer_use.contracts import (
            READ_TOOL_NAMES,
        )

        identifier(tool_name)
        for key in (
            "user_id",
            "tenant_id",
            "project_id",
            "conversation_id",
            "run_id",
            "session_id",
            "call_id",
        ):
            identifier(getattr(authorization, key))
        if (
            not isinstance(authorization.round, int)
            or isinstance(authorization.round, bool)
            or authorization.round < 0
            or authorization.authorization_revision < 1
            or authorization.permission_profile
            not in {"read_only", "workspace_write", "full_access"}
        ):
            raise DeviceBridgeError("computer_use_run_authorization_invalid")
        if (
            check_effect
            and effect not in {"read", "execute"}
            and tool_name not in READ_TOOL_NAMES
            and authorization.permission_profile != "full_access"
            and tool_name not in authorization.approved_tools
        ):
            raise DeviceBridgeError("computer_use_run_permission_denied")

    async def _eligible_devices(self, authorization: CallAuthorization) -> list[dict[str, Any]]:
        devices = await self.devices.list(
            user_id=authorization.user_id,
            tenant_id=authorization.tenant_id,
            project_id=authorization.project_id,
        )
        if authorization.device_id is not None:
            devices = [
                device for device in devices if device["device_id"] == authorization.device_id
            ]
        devices = [device for device in devices if device["tool_definitions"]]
        if not devices:
            raise DeviceBridgeError("computer_use_device_disconnected")
        return devices

    def _payload(
        self,
        authorization: CallAuthorization,
        tool_name: str,
        arguments: dict[str, Any],
        device: dict[str, Any],
    ) -> dict[str, Any]:
        definition = next(
            (item for item in device["tool_definitions"] if item["name"] == tool_name), None
        )
        if definition is None:
            raise DeviceBridgeError("computer_use_tool_unavailable")
        if definition["inputSchema"].get("x-cua-step-only") is True:
            raise DeviceBridgeError("computer_use_step_context_required")
        effect = tool_effect(tool_name, definition["inputSchema"], arguments)
        self._validate_authorization(authorization, tool_name, effect=effect)
        if tool_name == "computer_connector_call":
            require_connector_servers(
                definition["inputSchema"], arguments, authorization.allowed_mcp_servers
            )
        from src.infrastructure.agent.native_computer_use.catalog import require_mcp_server

        require_mcp_server(definition["inputSchema"], authorization.allowed_mcp_servers)
        input_json = encoded(arguments)
        if len(input_json.encode()) > 256 * 1024:
            raise DeviceBridgeError("computer_use_input_too_large")
        try:
            valid = validator(argument_schema(definition["inputSchema"])).is_valid(arguments)
        except Exception as exc:
            raise DeviceBridgeError("computer_use_invalid_schema") from exc
        if not valid:
            raise DeviceBridgeError("computer_use_invalid_params")
        request_id = self._request_id(authorization)
        return {
            **asdict(authorization),
            "allowed_mcp_servers": list(authorization.allowed_mcp_servers),
            "request_id": request_id,
            "device_id": device["device_id"],
            "connection_id": device["connection_id"],
            "tool_name": tool_name,
            "tool_effect": effect,
            "display_kind": definition["inputSchema"].get("x-agistack-display-kind"),
            "mcp_binding": definition["inputSchema"].get("x-cua-mcp-binding"),
            "input_json": input_json,
            "status": "requested",
            "expires_at": math.ceil(time.time() + self._request_timeout(tool_name, arguments)),
        }

    def _request_timeout(self, tool_name: str, arguments: dict[str, Any]) -> float:
        if tool_name != "cua_repl_js":
            return self.timeout
        duration = arguments.get("timeout_ms", 30_000)
        if not isinstance(duration, int) or isinstance(duration, bool):
            raise DeviceBridgeError("computer_use_invalid_params")
        return max(self.timeout, min(max(duration, 1), 300_000) / 1000 + 15)

    @staticmethod
    def _request_id(authorization: CallAuthorization) -> str:
        return digest(
            [
                authorization.user_id,
                authorization.tenant_id,
                authorization.project_id,
                authorization.run_id,
                authorization.session_id,
                authorization.round,
                authorization.call_id,
            ]
        )

    async def _previous_result(self, key: str, payload: dict[str, Any]) -> ToolResult:
        previous = await self.read(key)
        if previous is None or any(
            previous.get(name) != payload[name]
            for name in (
                "input_json",
                "user_id",
                "tenant_id",
                "project_id",
                "run_id",
                "session_id",
                "tool_name",
                "authorization_revision",
                "permission_profile",
                "allowed_mcp_servers",
                "mcp_binding",
                "display_kind",
            )
        ):
            raise DeviceBridgeError("computer_use_call_identity_conflict")
        if payload.get("device_id") is not None and payload["device_id"] != previous["device_id"]:
            raise DeviceBridgeError("computer_use_call_identity_conflict")
        if previous["status"] == "completed":
            return await self.result(previous)
        return unknown_result()

    async def _wait_result(self, request_id: str, expires_at: float) -> ToolResult:
        deadline = asyncio.get_running_loop().time() + max(0, expires_at - time.time())
        while asyncio.get_running_loop().time() < deadline:
            value = await self.read(request_key(request_id))
            if value is None or value["status"] == "unknown":
                return unknown_result()
            if value["status"] == "completed":
                return await self.result(value)
            await asyncio.sleep(0.1)
        await self.cancel_request(request_id)
        return unknown_result()

    async def dispatch(
        self, connection_id: str, kind: str, request_id: str, *, expires_at: int | None = None
    ) -> None:
        key = control_key(connection_id)
        fields: dict[FieldT, EncodableT] = {"type": kind, "request_id": request_id}
        if expires_at is not None:
            fields["expires_at"] = expires_at
        await self.redis.xadd(key, fields, maxlen=2048)
        await self.redis.expire(key, REQUEST_SECONDS)

    async def claim(self, request_id: str, *, user_id: str, device_id: str) -> dict[str, Any]:
        from src.infrastructure.agent.native_computer_use.browser_scope import browser_scope

        identifier(device_id)

        def change(value: dict[str, Any] | None) -> dict[str, Any]:
            if value is None or value["user_id"] != user_id or value["device_id"] != device_id:
                raise DeviceBridgeError("computer_use_request_access_denied")
            if value["status"] != "requested" or value["expires_at"] <= time.time():
                raise DeviceBridgeError("computer_use_request_already_claimed")
            browser_scope(value)
            return {**value, "status": "claimed"}

        value = await self.update(request_key(request_id), change)

        # The owner witness remains server-side; the authenticated claim supplies
        # only the identity whose lease the route has just revalidated.
        return {
            **{
                key: item
                for key, item in value.items()
                if key not in {"status", "connection_id", "child_owner_digest"}
            },
            "browser_scope": browser_scope(value),
        }

    async def cancel_request(self, request_id: str) -> None:
        value = await self.read(request_key(request_id))
        if value is None:
            return

        def change(current: dict[str, Any] | None) -> dict[str, Any]:
            if current is None:
                raise DeviceBridgeError("computer_use_request_missing")
            current["cancelled"] = True
            if current["status"] != "completed":
                current["status"] = "unknown"
            return current

        await self.update(request_key(request_id), change, extra=self.control_cancel_event)
        await self.dispatch(value["connection_id"], "computer_use_cancel", request_id)

    async def cancel_run(
        self, run_id: str, *, user_id: str, tenant_id: str, project_id: str
    ) -> None:
        for request_id in await self.members(run_key(user_id, tenant_id, project_id, run_id)):
            await self.cancel_request(string(request_id))

    async def cancel_device(
        self, *, connection_id: str, device_id: str, user_id: str, tenant_id: str, project_id: str
    ) -> None:
        """Revocation stops every resource owned by this exact registered device."""
        for request_id in await self.members(f"{control_key(connection_id)}:requests"):
            value = await self.read(request_key(request_id))
            if value is not None and all(
                value.get(key) == expected
                for key, expected in {
                    "connection_id": connection_id,
                    "device_id": device_id,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                }.items()
            ):
                await self.cancel_request(request_id)

    async def cancel_session(
        self, run_id: str, *, user_id: str, tenant_id: str, project_id: str, session_id: str
    ) -> None:
        for request_id in await self.members(run_key(user_id, tenant_id, project_id, run_id)):
            value = await self.read(request_key(string(request_id)))
            if value is not None and value["session_id"] == session_id:
                await self.cancel_request(string(request_id))

    async def cancel_conversation(
        self, conversation_id: str, *, user_id: str, tenant_id: str, project_id: str
    ) -> None:
        index = conversation_key(user_id, tenant_id, project_id, conversation_id)
        for request_id in await self.members(index):
            await self.cancel_request(string(request_id))


def unknown_result() -> ToolResult:
    return ToolResult(
        output=encoded({"error": "action_outcome_unknown", "retry_allowed": False}), is_error=True
    )
