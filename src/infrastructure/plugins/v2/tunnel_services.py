"""Generation-owned Provider/Consumer seams for tunnel connections."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from fastapi import WebSocket, WebSocketDisconnect

from .runtime import (
    AsyncDisposerV2,
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

logger = logging.getLogger(__name__)

TUNNEL_CONNECTION_PROVIDER_MODULE_V2 = "builtin://memstack/runtime/tunnel-connection-provider"
TUNNEL_CONNECTION_PROVIDER_SERVICE_V2 = "service:tunnel.connection-provider"
TUNNEL_APPLICATION_MODULE_V2 = "builtin://memstack/application/tunnel-services"
TUNNEL_APPLICATION_SERVICE_V2 = "service:application.tunnel-services"
TUNNEL_PROVIDER_INJECT_V2 = "provider"


@dataclass(frozen=True, kw_only=True)
class TunnelConnectionStatusV2:
    """Non-identifying status exposed across the application seam."""

    active_connections: int


@runtime_checkable
class TunnelConnectionProviderProtocolV2(Protocol):
    """Generation-owned connection registry selected by the active Profile."""

    async def handle_websocket(
        self,
        websocket: WebSocket,
        *,
        subprotocol: str | None = None,
    ) -> None: ...

    def status(self) -> TunnelConnectionStatusV2: ...

    async def dispose(self) -> None: ...


class GenerationTunnelConnectionProviderV2:
    """Keep accepted sockets inside one generation and clean them on disposal."""

    def __init__(self) -> None:  # pyright: ignore[reportMissingSuperCall]
        self._connections: dict[int, WebSocket] = {}

    async def handle_websocket(
        self,
        websocket: WebSocket,
        *,
        subprotocol: str | None = None,
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        connection_key = id(websocket)
        self._connections[connection_key] = websocket
        logger.info("Tunnel connected (total: %d)", len(self._connections))
        try:
            while True:
                data = await websocket.receive_text()
                logger.debug("Tunnel received %d bytes", len(data))
        except WebSocketDisconnect:
            pass
        finally:
            _ = self._connections.pop(connection_key, None)
            logger.info("Tunnel disconnected (remaining: %d)", len(self._connections))

    def status(self) -> TunnelConnectionStatusV2:
        return TunnelConnectionStatusV2(active_connections=len(self._connections))

    async def dispose(self) -> None:
        connections = tuple(self._connections.values())
        for websocket in connections:
            try:
                await websocket.close(code=1012, reason="Service restart")
            except Exception as error:
                logger.warning(
                    "Tunnel close failed during generation disposal (error_type=%s)",
                    type(error).__name__,
                )
        self._connections.clear()


@dataclass(frozen=True, kw_only=True)
class TunnelApplicationServicesV2:
    """Operation-owned tunnel seam consumed by HTTP and WebSocket handlers."""

    provider: TunnelConnectionProviderProtocolV2

    async def connect(
        self,
        websocket: WebSocket,
        *,
        subprotocol: str | None = None,
    ) -> None:
        await self.provider.handle_websocket(websocket, subprotocol=subprotocol)

    def status(self) -> TunnelConnectionStatusV2:
        return self.provider.status()


@runtime_checkable
class TunnelApplicationResolverProtocolV2(Protocol):
    """Resolve tunnel services through the Profile-declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> TunnelApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class TunnelApplicationResolverV2:
    """Consumer that does not import or select a concrete connection registry."""

    provider: TunnelConnectionProviderProtocolV2

    def resolve(self, operation: OperationContextV2) -> TunnelApplicationServicesV2:
        _ = operation.descriptor
        return TunnelApplicationServicesV2(provider=self.provider)


def _apply_tunnel_connection_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> AsyncDisposerV2:
    if config.get("strategy") != "generation-connection-registry":
        raise ValueError(
            "tunnel connection provider requires strategy generation-connection-registry"
        )
    provider = GenerationTunnelConnectionProviderV2()
    _ = context.provide(
        TUNNEL_CONNECTION_PROVIDER_SERVICE_V2,
        provider,
        label="tunnel-connection-provider",
    )
    return provider.dispose


def _apply_tunnel_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("tunnel resolver requires strategy operation-scoped-provider")
    provider = context.require(TUNNEL_PROVIDER_INJECT_V2)
    if not isinstance(provider, TunnelConnectionProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_tunnel_connection_provider",
            "tunnel provider inject does not implement the connection contract",
        )
    _ = context.provide(
        TUNNEL_APPLICATION_SERVICE_V2,
        TunnelApplicationResolverV2(provider=provider),
        label="tunnel-application",
    )


def tunnel_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent tunnel Provider and application Consumer definitions."""
    return (
        PluginDefinitionV2(
            module_ref=TUNNEL_CONNECTION_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TUNNEL_CONNECTION_PROVIDER_MODULE_V2),
            apply=_apply_tunnel_connection_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=TUNNEL_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TUNNEL_APPLICATION_MODULE_V2),
            apply=_apply_tunnel_application_v2,
        ),
    )


__all__ = [
    "TUNNEL_APPLICATION_MODULE_V2",
    "TUNNEL_APPLICATION_SERVICE_V2",
    "TUNNEL_CONNECTION_PROVIDER_MODULE_V2",
    "TUNNEL_CONNECTION_PROVIDER_SERVICE_V2",
    "TUNNEL_PROVIDER_INJECT_V2",
    "GenerationTunnelConnectionProviderV2",
    "TunnelApplicationResolverProtocolV2",
    "TunnelApplicationResolverV2",
    "TunnelApplicationServicesV2",
    "TunnelConnectionProviderProtocolV2",
    "TunnelConnectionStatusV2",
    "tunnel_service_definitions_v2",
]
