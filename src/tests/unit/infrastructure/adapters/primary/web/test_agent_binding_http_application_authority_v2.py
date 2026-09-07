"""HTTP authority coverage for generation-owned AgentBinding services."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.agent_binding_http_application_authority_v2 import (
    agent_binding_http_application_authority_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    current_operation_context_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "GET",
            "path": "/api/v1/agent/bindings",
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_binding_authority_binds_tenant_operation_and_request_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=994,
        version=994,
    )
    db = AsyncSession()
    authority_context = None
    authority = None
    try:
        async with pin_generation_v2(host):
            authority_context = agent_binding_http_application_authority_v2(
                request=_request(),
                current_user=cast(User, SimpleNamespace(id="user-a")),
                tenant_id="tenant-a",
                db=db,
            )
            authority = await authority_context.__aenter__()

            assert authority.tenant_id == "tenant-a"
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id is None
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert current_operation_context_v2() is authority.operation
            await authority_context.__aexit__(None, None, None)

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if authority_context is not None:
            await authority_context.__aexit__(None, None, None)
        await db.close()
        await host.close()
