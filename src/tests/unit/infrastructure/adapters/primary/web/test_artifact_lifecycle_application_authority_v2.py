"""Request-lifetime coverage for the Artifact lifecycle V2 authority."""

from __future__ import annotations

from inspect import getsource, signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.infrastructure.adapters.primary.web.artifact_lifecycle_application_authority_v2 import (
    ArtifactLifecycleApplicationAuthorityV2,
    _route_template,
    artifact_lifecycle_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import artifacts
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.artifact_lifecycle_services import (
    ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2,
    ArtifactLifecycleApplicationServiceV2,
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


def _request(
    *,
    path: str = "/api/v1/artifacts",
    route_template: str | None = "/api/v1/artifacts",
) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "app": FastAPI(),
        "headers": [],
        "method": "GET",
        "path": path,
        "query_string": b"project_id=project-a",
        "scheme": "http",
        "server": ("test", 80),
    }
    if route_template is not None:
        scope["route"] = SimpleNamespace(path=route_template)
    return Request(scope)


def test_unresolved_route_template_never_records_raw_artifact_id() -> None:
    request = _request(
        path="/api/v1/artifacts/artifact-sensitive-id",
        route_template=None,
    )

    route_template = _route_template(request)

    assert route_template == "-"
    assert "artifact-sensitive-id" not in route_template


async def test_authority_uses_pinned_generation_and_operation_metadata() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=162,
        version=162,
    )
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = artifact_lifecycle_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)
            expected = authority.operation.require(ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 162
            assert authority.db is db
            assert isinstance(expected, ArtifactLifecycleApplicationServiceV2)
            assert authority.artifact is expected.artifact
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": None,
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/artifacts",
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
        "src.infrastructure.adapters.primary.web.artifact_lifecycle_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = artifact_lifecycle_application_authority_dependency_v2(
        request=_request(),
        current_user=cast(User, SimpleNamespace(id="user-a")),
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_lifecycle_routes_depend_only_on_the_v2_authority() -> None:
    getter_parameters = signature(artifacts.get_artifact_service).parameters
    authority_parameter = getter_parameters["artifact_lifecycle_application"]
    assert authority_parameter.default.dependency is (
        artifact_lifecycle_application_authority_dependency_v2
    )
    assert authority_parameter.annotation in {
        "ArtifactLifecycleApplicationAuthorityV2",
        ArtifactLifecycleApplicationAuthorityV2,
    }
    assert "request" not in getter_parameters
    assert "db" not in getter_parameters

    for endpoint in (
        artifacts.list_artifacts,
        artifacts.get_artifact,
        artifacts.refresh_artifact_url,
        artifacts.delete_artifact,
    ):
        service_parameter = signature(endpoint).parameters["service"]
        assert service_parameter.default.dependency is artifacts.get_artifact_service

    source = getsource(artifacts)
    assert "_artifact_service:" not in source
    assert "global _artifact_service" not in source
    assert "get_app_container" not in source
