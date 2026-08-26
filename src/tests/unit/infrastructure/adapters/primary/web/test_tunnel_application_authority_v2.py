"""Generation and security-boundary tests for the Tunnel V2 authority."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.websockets import WebSocket

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web import tunnel_application_authority_v2 as subject
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import OperationContextV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.tunnel_services import TunnelConnectionStatusV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


@asynccontextmanager
async def _dependency_value(
    iterator: AsyncGenerator[Any, None],
) -> AsyncIterator[Any]:
    value = await anext(iterator)
    try:
        yield value
    finally:
        with suppress(StopAsyncIteration):
            await anext(iterator)
        await iterator.aclose()


def _request(path: str, *, method: str = "GET") -> Any:
    return SimpleNamespace(
        method=method,
        scope={"route": SimpleNamespace(path=path)},
    )


def _websocket(path: str = "/api/v1/tunnel/connect") -> WebSocket:
    return cast(
        WebSocket,
        SimpleNamespace(
            headers=Headers(
                raw=[
                    (
                        b"sec-websocket-protocol",
                        b"memstack.auth, ms_sk_test_value",
                    )
                ]
            ),
            scope={"route": SimpleNamespace(path=path)},
            close=AsyncMock(),
        ),
    )


async def _bootstrap_host(generation: int) -> PlatformPluginRuntimeHostV2:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=generation,
        version=generation,
    )
    assert publication.accepted is True
    return host


async def test_websocket_auth_rejection_does_not_resolve_a_generation_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _websocket()
    authenticate = AsyncMock(return_value=None)
    generation = Mock(side_effect=AssertionError("generation must not be resolved"))
    db = cast(Any, SimpleNamespace())
    monkeypatch.setattr(subject, "authenticate_websocket_or_close", authenticate)
    monkeypatch.setattr(subject, "current_generation_v2", generation)

    async with _dependency_value(
        subject.tunnel_websocket_application_authority_dependency_v2(
            websocket=websocket,
            token=None,
            db=db,
        )
    ) as authority:
        assert authority is None

    authenticate.assert_awaited_once_with(websocket, db, None)
    generation.assert_not_called()


async def test_websocket_authority_uses_tenant_scope_identity_and_route_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = await _bootstrap_host(61)
    generation = host.manager.current
    assert generation is not None
    websocket = _websocket()
    monkeypatch.setattr(subject, "current_generation_v2", lambda: generation)
    monkeypatch.setattr(
        subject,
        "authenticate_websocket_or_close",
        AsyncMock(return_value=("user-a", "tenant-a")),
    )
    try:
        async with _dependency_value(
            subject.tunnel_websocket_application_authority_dependency_v2(
                websocket=websocket,
                token=None,
                db=cast(Any, SimpleNamespace()),
            )
        ) as authority:
            assert isinstance(authority, subject.TunnelApplicationAuthorityV2)
            assert authority.operation.context.scope == ScopeV2(
                kind=ScopeKindV2.TENANT,
                tenant_id="tenant-a",
            )
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "websocket-authority",
                "path": "/api/v1/tunnel/connect",
            }
            assert "ms_sk_test_value" not in authority.operation.operation_id
            assert "ms_sk_test_value" not in str(
                authority.operation.require(OPERATION_METADATA_SERVICE_V2)
            )
            assert authority.subprotocol == "memstack.auth"
    finally:
        await host.close()


async def test_websocket_authority_keeps_its_pinned_generation_during_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = await _bootstrap_host(62)
    try:
        async with await host.acquire() as generation:
            monkeypatch.setattr(subject, "current_generation_v2", lambda: generation)
            async with subject.tunnel_application_authority_context_v2(
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
                identity={"tenant_id": "tenant-a", "user_id": "user-a"},
                metadata={
                    "kind": "websocket-authority",
                    "path": "/api/v1/tunnel/connect",
                },
                subprotocol="memstack.auth",
            ) as authority:
                await host.bootstrap(
                    profile_path=_PROFILE_PATH,
                    manifest_paths=(_MANIFEST_PATH,),
                    generation=63,
                    version=63,
                    nonce="tunnel-generation-63",
                )

                assert authority.operation.descriptor.generation == 62
                assert host.current_distribution is not None
                assert host.current_distribution.descriptor.generation == 63
    finally:
        await host.close()


async def test_admin_authority_checks_persisted_access_before_service_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_user = SimpleNamespace(id="user-a", is_superuser=False, roles=[])
    denied = AsyncMock(return_value=False)
    generation = Mock(side_effect=AssertionError("generation must not be resolved"))
    monkeypatch.setattr(subject, "has_global_admin_access", denied)
    monkeypatch.setattr(subject, "current_generation_v2", generation)
    dependency = subject.tunnel_admin_application_authority_dependency_v2(
        request=_request("/api/v1/admin/tunnel/status"),
        current_user=cast(Any, current_user),
        db=cast(Any, SimpleNamespace()),
    )

    with pytest.raises(HTTPException) as error:
        await anext(dependency)

    assert error.value.status_code == 403
    denied.assert_awaited_once()
    generation.assert_not_called()


async def test_admin_authority_uses_root_scope_and_route_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = await _bootstrap_host(64)
    generation = host.manager.current
    assert generation is not None
    current_user = SimpleNamespace(id="admin-a", is_superuser=True, roles=[])
    monkeypatch.setattr(subject, "current_generation_v2", lambda: generation)
    monkeypatch.setattr(subject, "has_global_admin_access", AsyncMock(return_value=True))
    try:
        async with _dependency_value(
            subject.tunnel_admin_application_authority_dependency_v2(
                request=_request("/api/v1/admin/tunnel/status"),
                current_user=cast(Any, current_user),
                db=cast(Any, SimpleNamespace()),
            )
        ) as authority:
            assert isinstance(authority, subject.TunnelApplicationAuthorityV2)
            assert authority.operation.context.scope == ScopeV2(kind=ScopeKindV2.ROOT)
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "user_id": "admin-a"
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/admin/tunnel/status",
            }
    finally:
        await host.close()


def test_status_payload_never_exposes_connection_identifiers() -> None:
    services = SimpleNamespace(
        status=Mock(return_value=TunnelConnectionStatusV2(active_connections=2))
    )
    authority = subject.TunnelApplicationAuthorityV2(
        operation=cast(OperationContextV2, SimpleNamespace()),
        services=cast(Any, services),
        subprotocol=None,
    )

    assert authority.status() == {"active_connections": 2}
