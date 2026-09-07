"""Request authority and handler coverage for the reflection V2 surface."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.reflection_application_authority_v2 import (
    ReflectionApplicationAuthorityV2,
    reflection_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import reflection
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
            "path": "/api/v1/projects/project-a/playbooks",
            "path_params": {"project_id": "project-a"},
            "query_string": b"tenant_id=tenant-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_generation_and_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=14,
        version=14,
    )
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = reflection_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 14
            assert authority.operation.context.scope.kind is ScopeKindV2.PROJECT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.db is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/projects/project-a/playbooks",
            }
            assert getattr(authority.services.membership, "_session", None) is db
            assert getattr(authority.services.playbooks, "_session", None) is db
            assert getattr(authority.services.verdicts, "_session", None) is db
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
        "src.infrastructure.adapters.primary.web.reflection_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = reflection_application_authority_dependency_v2(
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


@pytest.mark.parametrize(
    "handler",
    (reflection.list_playbooks, reflection.list_reflection_verdicts),
)
def test_reflection_handlers_require_only_the_v2_application_authority(handler: object) -> None:
    parameters = signature(handler).parameters
    parameter = parameters["reflection_application"]

    assert parameter.default.dependency is reflection_application_authority_dependency_v2
    assert parameter.annotation in {
        "ReflectionApplicationAuthorityV2",
        ReflectionApplicationAuthorityV2,
    }
    assert "db" not in parameters


def test_reflection_router_removes_static_sql_dependencies() -> None:
    assert "get_db" not in vars(reflection)
    assert "SqlPlaybookRepository" not in vars(reflection)
    assert "SqlReflectionVerdictRepository" not in vars(reflection)


async def test_list_playbooks_reads_membership_and_repository_from_authority() -> None:
    membership = SimpleNamespace(contains=AsyncMock(return_value=True))
    playbooks = SimpleNamespace(
        find_by_project=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id="playbook-a",
                    project_id="project-a",
                    name="Recover",
                    status=SimpleNamespace(value="active"),
                    trigger=SimpleNamespace(
                        description="Repeated failure",
                        friction_kinds=("test",),
                        lane_transitions=(("plan", "execute"),),
                    ),
                    steps=(
                        SimpleNamespace(order=1, instruction="Inspect", rationale="Find cause"),
                    ),
                    hit_count=2,
                    last_used_at=None,
                    created_at=SimpleNamespace(isoformat=lambda: "2026-08-23T00:00:00+00:00"),
                    updated_at=SimpleNamespace(isoformat=lambda: "2026-08-23T00:01:00+00:00"),
                )
            ]
        )
    )
    authority = SimpleNamespace(
        services=SimpleNamespace(
            membership=membership,
            playbooks=playbooks,
            verdicts=SimpleNamespace(),
        )
    )

    response = await reflection.list_playbooks(
        project_id="project-a",
        limit=25,
        current_user=cast(User, SimpleNamespace(id="user-a")),
        reflection_application=authority,
    )

    assert response.items[0].id == "playbook-a"
    assert response.items[0].trigger["lane_transitions"] == [["plan", "execute"]]
    membership.contains.assert_awaited_once_with(user_id="user-a", project_id="project-a")
    playbooks.find_by_project.assert_awaited_once_with("project-a", limit=25)


async def test_reflection_handler_rejects_a_non_member_before_repository_access() -> None:
    membership = SimpleNamespace(contains=AsyncMock(return_value=False))
    verdicts = SimpleNamespace(list_for_project=AsyncMock())
    authority = SimpleNamespace(
        services=SimpleNamespace(
            membership=membership,
            playbooks=SimpleNamespace(),
            verdicts=verdicts,
        )
    )

    with pytest.raises(HTTPException) as error:
        await reflection.list_reflection_verdicts(
            project_id="project-a",
            limit=10,
            current_user=cast(User, SimpleNamespace(id="user-a")),
            reflection_application=authority,
        )

    assert error.value.status_code == 403
    verdicts.list_for_project.assert_not_awaited()
