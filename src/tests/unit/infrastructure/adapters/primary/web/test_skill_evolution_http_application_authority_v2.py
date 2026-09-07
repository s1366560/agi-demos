"""Request-lifetime coverage for the composite SkillEvolution V2 authority."""

from __future__ import annotations

from collections.abc import AsyncIterator
from inspect import getsource, signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.routers import skills
from src.infrastructure.adapters.primary.web.skill_evolution_http_application_authority_v2 import (
    skill_evolution_http_application_authority_v2,
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
            "path": "/api/v1/skills/evolution/overview",
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_resolves_all_repositories_from_one_pinned_operation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1027,
        version=1027,
    )
    assert publication.accepted is True, publication.receipt
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    authority = None
    try:
        async with (
            pin_generation_v2(host),
            skill_evolution_http_application_authority_v2(
                request=_request(),
                tenant_id="tenant-a",
                current_user=user,
                db=db,
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 1027
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.db is db
            assert authority.evolution_repository._session is db
            assert authority.skill_repository._session is db
            assert authority.skill_version_repository._session is db
            assert authority.plugin_config_repository._session is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/skills/evolution/overview",
            }

        assert authority is not None
        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


def test_read_handlers_resolve_repositories_only_from_composite_v2_authority() -> None:
    overview_dependencies = {
        "evolution_repository": skills._get_skill_evolution_repository_v2,
        "plugin_config_repository": skills._get_skill_evolution_plugin_config_repository_v2,
    }
    detail_dependencies = {
        "evolution_repository": skills._get_skill_evolution_repository_v2,
        "skill_repository": skills._get_skill_evolution_skill_repository_v2,
        "skill_version_repository": skills._get_skill_evolution_version_repository_v2,
        "plugin_config_repository": skills._get_skill_evolution_plugin_config_repository_v2,
    }
    for parameter_name, dependency in overview_dependencies.items():
        parameter = signature(skills.get_skill_evolution_overview).parameters[parameter_name]
        assert parameter.default.dependency is dependency
    for parameter_name, dependency in detail_dependencies.items():
        parameter = signature(skills.get_skill_evolution).parameters[parameter_name]
        assert parameter.default.dependency is dependency

    for dependency in set(overview_dependencies.values()) | set(detail_dependencies.values()):
        authority = signature(dependency).parameters["authority"]
        assert authority.default.dependency is skills._get_skill_evolution_authority_v2

    for endpoint in (skills.get_skill_evolution_overview, skills.get_skill_evolution):
        source = getsource(endpoint)
        assert "SkillEvolutionRepository(" not in source
        assert "SqlSkillVersionRepository(" not in source

    reject_parameter = signature(skills.reject_skill_evolution_job).parameters[
        "evolution_repository"
    ]
    assert reject_parameter.default.dependency is skills._get_skill_evolution_repository_v2
    reject_source = getsource(skills.reject_skill_evolution_job)
    assert "SkillEvolutionRepository(" not in reject_source

    apply_dependencies = {
        "evolution_repository": skills._get_skill_evolution_repository_v2,
        "skill_repository": skills._get_skill_evolution_skill_repository_v2,
        "skill_version_repository": skills._get_skill_evolution_version_repository_v2,
    }
    for parameter_name, dependency in apply_dependencies.items():
        parameter = signature(skills.apply_skill_evolution_job).parameters[parameter_name]
        assert parameter.default.dependency is dependency
    apply_source = getsource(skills.apply_skill_evolution_job)
    assert "SkillEvolutionRepository(" not in apply_source
    assert "SqlSkillVersionRepository(" not in apply_source


def test_fastapi_shares_one_authority_for_all_repository_dependencies() -> None:
    app = FastAPI()
    authority = SimpleNamespace(
        evolution_repository=object(),
        skill_repository=object(),
        skill_version_repository=object(),
        plugin_config_repository=object(),
    )
    lifecycle: list[str] = []

    async def fake_authority() -> AsyncIterator[Any]:
        lifecycle.append("enter")
        yield authority
        lifecycle.append("exit")

    async def probe(
        evolution_repository: Any = Depends(skills._get_skill_evolution_repository_v2),
        skill_repository: Any = Depends(skills._get_skill_evolution_skill_repository_v2),
        skill_version_repository: Any = Depends(skills._get_skill_evolution_version_repository_v2),
        plugin_config_repository: Any = Depends(
            skills._get_skill_evolution_plugin_config_repository_v2
        ),
    ) -> dict[str, bool]:
        lifecycle.append("handler")
        return {
            "evolution": evolution_repository is authority.evolution_repository,
            "skill": skill_repository is authority.skill_repository,
            "version": skill_version_repository is authority.skill_version_repository,
            "plugin_config": plugin_config_repository is authority.plugin_config_repository,
        }

    app.dependency_overrides[skills._get_skill_evolution_authority_v2] = fake_authority
    _ = app.get("/probe")(probe)

    with TestClient(app) as client:
        response = client.get("/probe")

    assert response.json() == {
        "evolution": True,
        "skill": True,
        "version": True,
        "plugin_config": True,
    }
    assert lifecycle == ["enter", "handler", "exit"]


async def test_authority_fails_closed_without_a_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web."
        "skill_evolution_http_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with skill_evolution_http_application_authority_v2(
                request=_request(),
                tenant_id="tenant-a",
                current_user=cast(User, SimpleNamespace(id="user-a")),
                db=db,
            ):
                pass
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"
