"""V2 Provider/Consumer and lifecycle coverage for tunnel services."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from starlette.datastructures import Headers
from starlette.websockets import WebSocket, WebSocketDisconnect

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.tunnel_services import (
    TUNNEL_APPLICATION_MODULE_V2,
    TUNNEL_APPLICATION_SERVICE_V2,
    TUNNEL_CONNECTION_PROVIDER_MODULE_V2,
    TUNNEL_CONNECTION_PROVIDER_SERVICE_V2,
    GenerationTunnelConnectionProviderV2,
    TunnelApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _BlockingWebSocket:
    def __init__(self, *, close_error: Exception | None = None) -> None:
        self.headers = Headers(raw=[])
        self.accepted = asyncio.Event()
        self.closed = asyncio.Event()
        self.accepted_subprotocol: str | None = None
        self.close_code: int | None = None
        self.close_error = close_error

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_subprotocol = subprotocol
        self.accepted.set()

    async def receive_text(self) -> str:
        await self.closed.wait()
        raise WebSocketDisconnect(code=self.close_code or 1000)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        _ = reason
        self.close_code = code
        self.closed.set()
        if self.close_error is not None:
            raise self.close_error


async def test_application_resolver_uses_the_profile_selected_provider_alias() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=51,
        version=51,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="websocket-tunnel:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            resolver = operation.require(TUNNEL_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, TunnelApplicationResolverV2)
            assert resolver.resolve(operation).status().active_connections == 0
    finally:
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    provider = next(
        entry
        for entry in document.entries
        if entry.module_ref == TUNNEL_CONNECTION_PROVIDER_MODULE_V2
    )
    consumer = next(
        entry for entry in document.entries if entry.module_ref == TUNNEL_APPLICATION_MODULE_V2
    )

    assert provider.enabled is True
    assert consumer.enabled is True
    assert document.entries.index(provider) < document.entries.index(consumer)
    assert consumer.inject == {"provider": TUNNEL_CONNECTION_PROVIDER_SERVICE_V2}


async def test_application_resolver_rejects_a_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == TUNNEL_CONNECTION_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=52,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-tunnel-services" in str(error.value)


async def test_generation_disposer_closes_connections_and_clears_provider_state() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=53,
        version=53,
    )
    assert publication.accepted is True
    generation = host.manager.current
    assert generation is not None
    provider = generation.resolve(
        TUNNEL_CONNECTION_PROVIDER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(provider, GenerationTunnelConnectionProviderV2)
    websocket = _BlockingWebSocket()
    connection = asyncio.create_task(
        provider.handle_websocket(
            cast(WebSocket, websocket),
            subprotocol="memstack.auth",
        )
    )
    await websocket.accepted.wait()

    assert provider.status().active_connections == 1
    assert websocket.accepted_subprotocol == "memstack.auth"

    await host.close()
    await connection

    assert websocket.close_code == 1012
    assert provider.status().active_connections == 0


async def test_provider_cleanup_continues_after_one_socket_close_fails() -> None:
    provider = GenerationTunnelConnectionProviderV2()
    first = _BlockingWebSocket(close_error=ValueError("close failed"))
    second = _BlockingWebSocket()
    connections = tuple(
        asyncio.create_task(provider.handle_websocket(cast(WebSocket, websocket)))
        for websocket in (first, second)
    )
    await asyncio.gather(first.accepted.wait(), second.accepted.wait())

    await provider.dispose()
    await asyncio.gather(*connections)

    assert first.close_code == 1012
    assert second.close_code == 1012
    assert provider.status().active_connections == 0
