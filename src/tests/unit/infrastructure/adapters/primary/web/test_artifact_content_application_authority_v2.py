"""Request-lifetime coverage for the Artifact content V2 authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.infrastructure.adapters.primary.web.artifact_content_application_authority_v2 import (
    ArtifactContentApplicationAuthorityV2,
    artifact_content_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import artifacts
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
            "path": "/api/v1/artifacts/artifact-a/content",
            "path_params": {"artifact_id": "artifact-a"},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_generation_and_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=159,
        version=159,
    )
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = artifact_content_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 159
            assert authority.db is db
            assert authority.services.content._repository._session is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": None,
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/artifacts/artifact-a/content",
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
        "src.infrastructure.adapters.primary.web.artifact_content_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = artifact_content_application_authority_dependency_v2(
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


def test_router_getters_delegate_only_to_the_v2_authority() -> None:
    for dependency in (
        artifacts.get_artifact_content_authority_service,
        artifacts.get_artifact_content_commit_reconciler,
    ):
        parameters = signature(dependency).parameters
        authority_parameter = parameters["artifact_content_application"]
        assert authority_parameter.default.dependency is (
            artifact_content_application_authority_dependency_v2
        )
        assert authority_parameter.annotation in {
            "ArtifactContentApplicationAuthorityV2",
            ArtifactContentApplicationAuthorityV2,
        }
        assert "request" not in parameters
        assert "db" not in parameters
