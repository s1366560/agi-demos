"""Request-lifetime coverage for the unified Artifact HTTP V2 authority."""

from __future__ import annotations

from inspect import getsource, signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.infrastructure.adapters.primary.web.artifact_http_application_authority_v2 import (
    ArtifactHttpApplicationAuthorityV2,
    _route_template,
    artifact_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import artifacts
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.artifact_http_services import (
    ARTIFACT_HTTP_APPLICATION_SERVICE_V2,
    ArtifactHttpApplicationResolverProtocolV2,
)
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


def _request(*, route_template: str | None = "/api/v1/artifacts/{artifact_id}") -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "app": FastAPI(),
        "headers": [],
        "method": "GET",
        "path": "/api/v1/artifacts/artifact-sensitive-id",
        "path_params": {"artifact_id": "artifact-sensitive-id"},
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
    }
    if route_template is not None:
        scope["route"] = SimpleNamespace(path=route_template)
    return Request(scope)


def test_unresolved_route_template_never_records_raw_artifact_id() -> None:
    route_template = _route_template(_request(route_template=None))

    assert route_template == "-"
    assert "artifact-sensitive-id" not in route_template


async def test_authority_resolves_one_operation_owned_artifact_http_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=166,
        version=166,
    )
    db = AsyncSession()
    user = cast(
        User,
        SimpleNamespace(id="user-a", is_superuser=False),
    )
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = artifact_http_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)
            resolver = authority.operation.require(ARTIFACT_HTTP_APPLICATION_SERVICE_V2)

            assert isinstance(authority, ArtifactHttpApplicationAuthorityV2)
            assert isinstance(resolver, ArtifactHttpApplicationResolverProtocolV2)
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 166
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": None,
                "user_id": "user-a",
                "is_superuser": False,
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/artifacts/{artifact_id}",
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
        "src.infrastructure.adapters.primary.web.artifact_http_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = artifact_http_application_authority_dependency_v2(
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


def test_all_artifact_routes_depend_only_on_the_unified_v2_authority() -> None:
    endpoints = (
        artifacts.list_artifacts,
        artifacts.get_artifact,
        artifacts.download_artifact,
        artifacts.get_artifact_content,
        artifacts.get_artifact_content_bytes,
        artifacts.refresh_artifact_url,
        artifacts.update_artifact_content,
        artifacts.delete_artifact,
        artifacts.list_categories,
    )
    for endpoint in endpoints:
        parameters = signature(endpoint).parameters
        authority_parameter = parameters["artifact_application"]
        assert authority_parameter.default.dependency is (
            artifact_http_application_authority_dependency_v2
        )
        assert authority_parameter.annotation in {
            "ArtifactHttpApplicationAuthorityV2",
            ArtifactHttpApplicationAuthorityV2,
        }
        assert not {"current_user", "db", "service", "reconciler"}.intersection(parameters)

    source = getsource(artifacts)
    for forbidden in (
        "get_current_user",
        "get_db",
        "UserProject",
        "refresh_select_statement",
        "verify_project_access",
        "get_artifact_service",
        "get_artifact_content_authority_service",
        "get_artifact_content_commit_reconciler",
    ):
        assert forbidden not in source
