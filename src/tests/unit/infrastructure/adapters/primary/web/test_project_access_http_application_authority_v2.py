"""Request authority coverage for generation-owned project membership checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.infrastructure.adapters.primary.web.project_access_http_application_authority_v2 import (
    project_access_http_application_authority_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.project_access_services import SqlProjectAccessTransactionV2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
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
            "path": "/api/v1/agent/conversations",
            "query_string": b"project_id=project-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_project_access_authority_pins_project_scope_and_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=983,
        version=983,
    )
    db = AsyncSession()
    authority_context = None
    authority = None
    try:
        async with pin_generation_v2(host):
            authority_context = project_access_http_application_authority_v2(
                request=_request(),
                project_id="project-a",
                current_user=cast(User, SimpleNamespace(id="user-a")),
                tenant_id="tenant-a",
                db=db,
            )
            authority = await authority_context.__aenter__()

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 983
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "project_id": "project-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/agent/conversations",
            }
            assert isinstance(authority.service.transaction, SqlProjectAccessTransactionV2)
            assert authority.service.transaction.db is db
            await authority_context.__aexit__(None, None, None)

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if authority_context is not None:
            await authority_context.__aexit__(None, None, None)
        await db.close()
        await host.close()


async def test_project_access_authority_fails_closed_without_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.project_access_http_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    authority_context = project_access_http_application_authority_v2(
        request=_request(),
        project_id="project-a",
        current_user=cast(User, SimpleNamespace(id="user-a")),
        tenant_id="tenant-a",
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await authority_context.__aenter__()
    finally:
        await authority_context.__aexit__(None, None, None)
        await db.close()

    assert error.value.code == "generation_not_pinned"
