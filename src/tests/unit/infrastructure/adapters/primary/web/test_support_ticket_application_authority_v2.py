"""Request authority and handler coverage for the support-ticket V2 surface."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.routers import support
from src.infrastructure.adapters.primary.web.support_ticket_application_authority_v2 import (
    SupportTicketApplicationAuthorityV2,
    support_ticket_application_authority_dependency_v2,
)
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
            "method": "GET",
            "path": "/api/v1/support/tickets",
            "path_params": {},
            "query_string": b"tenant_id=tenant-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_generation_identity_and_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=84,
        version=84,
    )
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = support_ticket_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 84
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.db is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
                "is_superuser": False,
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/support/tickets",
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
        "src.infrastructure.adapters.primary.web.support_ticket_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = support_ticket_application_authority_dependency_v2(
        request=_request(),
        current_user=cast(User, SimpleNamespace(id="user-a", is_superuser=False)),
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_support_router_removes_static_persistence_and_tenant_access_logic() -> None:
    for symbol in (
        "SupportTicket",
        "UserTenant",
        "select",
        "func",
        "refresh_select_statement",
        "get_db",
        "_require_support_tenant_access",
    ):
        assert symbol not in vars(support)


@pytest.mark.parametrize(
    "handler",
    (
        support.create_support_ticket,
        support.list_support_tickets,
        support.get_support_ticket,
        support.update_support_ticket,
        support.close_support_ticket,
    ),
)
def test_support_handlers_require_only_v2_application_authority(handler: object) -> None:
    parameters = signature(handler).parameters
    parameter = parameters["support_application"]

    assert parameter.default.dependency is support_ticket_application_authority_dependency_v2
    assert parameter.annotation in {
        "SupportTicketApplicationAuthorityV2",
        SupportTicketApplicationAuthorityV2,
    }
    assert "db" not in parameters
