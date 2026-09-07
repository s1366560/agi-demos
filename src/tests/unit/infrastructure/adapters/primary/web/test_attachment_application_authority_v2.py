"""Request-lifetime coverage for the attachment application V2 authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.application.services.attachment_service import AttachmentService
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.attachment_application_authority_v2 import (
    AttachmentApplicationAuthorityV2,
    _route_template,
    attachment_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import attachments_upload
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
            "path": "/api/v1/attachments/private-id",
            "path_params": {"attachment_id": "private-id"},
            "query_string": b"",
            "route": SimpleNamespace(path="/api/v1/attachments/{attachment_id}"),
            "scheme": "http",
            "server": ("test", 80),
        }
    )


def _user() -> User:
    return cast(User, SimpleNamespace(id="user-a", is_superuser=False))


def test_unresolved_route_template_never_records_raw_request_path() -> None:
    request = _request()
    request.scope.pop("route")

    route_template = _route_template(request)

    assert route_template == "-"
    assert "private-id" not in route_template


async def test_authority_uses_pinned_generation_identity_and_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=153,
        version=153,
    )
    db = AsyncSession()
    user = _user()
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = attachment_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 153
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.db is db
            assert authority.current_user is user
            assert isinstance(authority.services.attachments.service, AttachmentService)
            assert getattr(authority.services.attachments.service._repo, "_session", None) is db
            assert getattr(authority.services.attachments.access, "_session", None) is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": None,
                "user_id": "user-a",
                "is_superuser": False,
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/attachments/{attachment_id}",
            }
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
        "src.infrastructure.adapters.primary.web.attachment_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = attachment_application_authority_dependency_v2(
        request=_request(),
        current_user=_user(),
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_every_router_handler_resolves_only_from_v2_authority() -> None:
    for handler_name in (
        "initiate_multipart_upload",
        "upload_part",
        "complete_multipart_upload",
        "abort_multipart_upload",
        "upload_simple",
        "list_attachments",
        "get_attachment",
        "download_attachment",
        "delete_attachment",
    ):
        parameters = signature(getattr(attachments_upload, handler_name)).parameters
        authority = parameters["attachment_application"]

        assert authority.default.dependency is attachment_application_authority_dependency_v2
        assert authority.annotation in {
            "AttachmentApplicationAuthorityV2",
            AttachmentApplicationAuthorityV2,
        }
        assert "current_user" not in parameters
        assert "db" not in parameters
        assert "attachment_service" not in parameters
