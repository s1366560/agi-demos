"""Authenticated Computer Use registration and typed result channels."""

from __future__ import annotations

from typing import Any

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, identifier
from src.infrastructure.agent.native_computer_use.websocket import STATE_KEY, DeviceConnection
from src.infrastructure.i18n import gettext as _


class ComputerUseHandler(WebSocketMessageHandler):
    """Protocol membership is static; execution remains in the approved agent tool."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    @property
    def message_type(self) -> str:
        return self.kind

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        try:
            await self._handle(context, message)
        except DeviceBridgeError as exc:
            await context.send_error(_("Computer Use device request rejected"), code=str(exc))
        except Exception:
            # Transport payloads may contain image bytes or user input. Do not
            # pass their exception representations to the generic router logger.
            await context.send_error(
                _("Computer Use device transport unavailable"),
                code="computer_use_transport_unavailable",
            )

    async def _handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        redis = context.container.redis_client
        if redis is None:
            raise DeviceBridgeError("computer_use_transport_unavailable")
        state = context.websocket.scope.get(STATE_KEY)
        if self.kind == "computer_use_device":
            from src.infrastructure.adapters.primary.web.routers.agent.computer_use_device import (
                require_project_access,
            )

            scope = message.get("scope")
            if not isinstance(scope, dict) or scope.get("tenant_id") != context.tenant_id:
                raise DeviceBridgeError("computer_use_scope_denied")
            project_id = identifier(scope.get("project_id"))
            await require_project_access(context.db, context.user_id, context.tenant_id, project_id)
            if state is None:
                state = DeviceConnection(redis=redis, websocket=context.websocket)
                context.websocket.scope[STATE_KEY] = state
            if not isinstance(state, DeviceConnection):
                raise DeviceBridgeError("computer_use_connection_invalid")
            definitions = message.get("tool_definitions")
            if not isinstance(definitions, list) or any(
                not isinstance(item, dict) for item in definitions
            ):
                raise DeviceBridgeError("computer_use_invalid_catalog")
            device_id = identifier(message.get("device_id"))
            await NativeComputerBroker(redis).devices.register(
                DeviceScope(
                    user_id=context.user_id,
                    tenant_id=context.tenant_id,
                    project_id=project_id,
                    device_id=device_id,
                ),
                state.connection_id,
                definitions,
            )
            state.start()
            if not definitions:
                await NativeComputerBroker(redis).cancel_device(
                    connection_id=state.connection_id,
                    device_id=device_id,
                    user_id=context.user_id,
                    tenant_id=context.tenant_id,
                    project_id=project_id,
                )
            await context.send_json(
                {
                    "type": "computer_use_device_ready",
                    "device_id": device_id,
                    "ready": bool(definitions),
                }
            )
            return
        if not isinstance(state, DeviceConnection):
            raise DeviceBridgeError("computer_use_device_not_registered")
        broker = NativeComputerBroker(redis)
        if self.kind == "computer_use_result":
            await broker.receive_result(state.connection_id, message)
        elif self.kind == "computer_use_media":
            await broker.receive_chunk(state.connection_id, message)
        elif self.kind == "computer_use_control_state":
            await broker.receive_control_state(state.connection_id, message)
