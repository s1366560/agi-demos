"""Request authority coverage for generation-owned conversation collections."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.infrastructure.adapters.primary.web.conversation_collection_http_application_authority_v2 import (
    conversation_create_http_application_authority_dependency_v2,
    conversation_list_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.conversation_collection_repository import (
    SqlConversationCollectionRepositoryV2,
)
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]


def _request(
    *,
    method: str,
    path: str,
    query_string: bytes = b"",
    json_body: dict[str, object] | None = None,
) -> Request:
    body = json.dumps(json_body).encode() if json_body is not None else b""
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [(b"content-type", b"application/json")],
            "method": method,
            "path": path,
            "query_string": query_string,
            "scheme": "http",
            "server": ("test", 80),
        },
        receive=receive,
    )


def test_create_openapi_keeps_the_existing_request_body_shape() -> None:
    from src.infrastructure.adapters.primary.web.routers.agent.conversations import router

    app = FastAPI()
    app.include_router(router)

    operation = app.openapi()["paths"]["/conversations"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert schema == {
        "$ref": "#/components/schemas/CreateConversationRequest",
    }


async def test_create_authority_uses_body_project_and_pinned_generation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=951,
        version=951,
    )
    db = AsyncSession()
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = conversation_create_http_application_authority_dependency_v2(
                request=_request(
                    method="POST",
                    path="/api/v1/agent/conversations",
                    json_body={"project_id": "project-a"},
                ),
                current_user=cast(User, SimpleNamespace(id="user-a")),
                tenant_id="tenant-a",
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 951
            assert authority.operation.context.scope.kind.value == "project"
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
                "project_id": "project-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/agent/conversations",
            }
            assert isinstance(authority.service.repository, SqlConversationCollectionRepositoryV2)
            assert authority.service.repository.session is db
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


async def test_list_authority_uses_query_project_and_disposes() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=952,
        version=952,
    )
    db = AsyncSession()
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = conversation_list_http_application_authority_dependency_v2(
                request=_request(
                    method="GET",
                    path="/api/v1/agent/conversations",
                    query_string=b"project_id=project-a",
                ),
                project_id="project-a",
                current_user=cast(User, SimpleNamespace(id="user-a")),
                tenant_id="tenant-a",
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 952
            assert authority.operation.context.scope.project_id == "project-a"
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


async def test_collection_authority_fails_closed_without_a_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.conversation_collection_http_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = conversation_list_http_application_authority_dependency_v2(
        request=_request(method="GET", path="/api/v1/agent/conversations"),
        project_id="project-a",
        current_user=cast(User, SimpleNamespace(id="user-a")),
        tenant_id="tenant-a",
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"
