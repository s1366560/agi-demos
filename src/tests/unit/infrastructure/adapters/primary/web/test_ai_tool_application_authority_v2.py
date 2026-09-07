"""Request authority and handler coverage for the ai-tools V2 surface."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.ai_tool_application_authority_v2 import (
    AiToolApplicationAuthorityV2,
    ai_tool_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import ai_tools
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
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
            "method": "POST",
            "path": "/api/v1/ai/optimize",
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_generation_identity_and_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=94,
        version=94,
    )
    db = AsyncSession()
    user = cast(
        User,
        SimpleNamespace(id="user-a", tenant_id="tenant-a", is_superuser=False),
    )
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = ai_tool_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 94
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.db is db
            assert authority.user_id == "user-a"
            assert authority.tenant_id == "tenant-a"
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
                "is_superuser": False,
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/ai/optimize",
            }
            assert getattr(authority.services.persistence, "_session", None) is db
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


async def test_authority_fails_closed_without_a_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.ai_tool_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = ai_tool_application_authority_dependency_v2(
        request=_request(),
        current_user=cast(
            User,
            SimpleNamespace(id="user-a", tenant_id=None, is_superuser=False),
        ),
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_ai_tools_router_removes_static_llm_and_persistence_resolution() -> None:
    for symbol in (
        "create_llm_client",
        "get_ai_tools_llm_client",
        "get_db",
        "select",
        "UserTenant",
        "refresh_select_statement",
    ):
        assert symbol not in vars(ai_tools)


@pytest.mark.parametrize(
    "handler",
    (ai_tools.optimize_content, ai_tools.generate_title),
)
def test_ai_tool_handlers_require_only_v2_application_authority(handler: object) -> None:
    parameters = signature(handler).parameters
    parameter = parameters["ai_tool_application"]

    assert parameter.default.dependency is ai_tool_application_authority_dependency_v2
    assert parameter.annotation in {
        "AiToolApplicationAuthorityV2",
        AiToolApplicationAuthorityV2,
    }
    assert "llm_client" not in parameters


async def test_optimize_content_resolves_client_through_v2_service() -> None:
    client = SimpleNamespace(generate=AsyncMock(return_value={"content": " Improved "}))
    services = SimpleNamespace(resolve_client=AsyncMock(return_value=client))

    result = await ai_tools.optimize_content(
        ai_tools.OptimizeRequest(content="Original", instruction="Improve"),
        ai_tool_application=SimpleNamespace(
            user_id="user-a",
            tenant_id="tenant-a",
            services=services,
        ),
    )

    assert result == ai_tools.OptimizeResponse(content="Improved")
    services.resolve_client.assert_awaited_once_with(
        user_id="user-a",
        tenant_id="tenant-a",
    )


async def test_unavailable_v2_client_preserves_public_501() -> None:
    from src.infrastructure.plugins.v2.ai_tool_services import AiToolClientUnavailableV2

    services = SimpleNamespace(resolve_client=AsyncMock(side_effect=AiToolClientUnavailableV2))

    with pytest.raises(ai_tools.HTTPException) as error:
        await ai_tools.generate_title(
            ai_tools.TitleRequest(content="Original"),
            ai_tool_application=SimpleNamespace(
                user_id="user-a",
                tenant_id=None,
                services=services,
            ),
        )

    assert error.value.status_code == 501
    assert error.value.detail == ai_tools.LLM_CLIENT_UNAVAILABLE_DETAIL
