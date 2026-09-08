"""Request authority and handler coverage for the project schema V2 surface."""

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

from src.application.schemas.schema import EntityTypeCreate
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.routers import schema
from src.infrastructure.adapters.primary.web.schema_application_authority_v2 import (
    SchemaApplicationAuthorityV2,
    schema_application_authority_dependency_v2,
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
from src.infrastructure.plugins.v2.schema_services import SchemaEntityTypeConflictV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "GET",
            "path": "/api/v1/projects/project-a/schema/entities",
            "path_params": {"project_id": "project-a"},
            "query_string": b"tenant_id=tenant-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_generation_and_operation_session(monkeypatch) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=23,
        version=23,
    )
    db = AsyncSession()
    monkeypatch.setattr(
        db,
        "execute",
        AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: ("tenant-a", "member"))),
    )
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = schema_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 23
            assert authority.operation.context.scope.kind is ScopeKindV2.PROJECT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.db is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "project_id": "project-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/projects/project-a/schema/entities",
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
        "src.infrastructure.adapters.primary.web.schema_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = schema_application_authority_dependency_v2(
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
    (
        schema.list_entity_types,
        schema.create_entity_type,
        schema.update_entity_type,
        schema.delete_entity_type,
        schema.list_edge_types,
        schema.create_edge_type,
        schema.update_edge_type,
        schema.delete_edge_type,
        schema.list_edge_maps,
        schema.create_edge_map,
        schema.delete_edge_map,
    ),
)
def test_schema_handlers_require_only_the_v2_application_authority(handler: object) -> None:
    parameters = signature(handler).parameters
    parameter = parameters["schema_application"]

    assert parameter.default.dependency is schema_application_authority_dependency_v2
    assert parameter.annotation in {"SchemaApplicationAuthorityV2", SchemaApplicationAuthorityV2}
    assert "db" not in parameters


def test_schema_router_removes_static_sql_dependencies() -> None:
    assert "get_db" not in vars(schema)
    assert "verify_project_access" not in vars(schema)
    assert "EntityType" not in vars(schema)
    assert "EdgeType" not in vars(schema)
    assert "EdgeTypeMap" not in vars(schema)
    assert "UserProject" not in vars(schema)


async def test_list_entity_types_delegates_identity_and_project_to_v2_service() -> None:
    services = SimpleNamespace(list_entity_types=AsyncMock(return_value=[]))

    result = await schema.list_entity_types(
        project_id="project-a",
        current_user=cast(User, SimpleNamespace(id="user-a")),
        schema_application=SimpleNamespace(services=services),
    )

    assert result == []
    services.list_entity_types.assert_awaited_once_with(
        user_id="user-a",
        project_id="project-a",
    )


async def test_create_entity_type_translates_typed_conflict_without_db_fallback() -> None:
    services = SimpleNamespace(
        create_entity_type=AsyncMock(side_effect=SchemaEntityTypeConflictV2())
    )

    with pytest.raises(HTTPException) as error:
        await schema.create_entity_type(
            project_id="project-a",
            entity_data=EntityTypeCreate(name="Person", schema={"fields": []}),
            current_user=cast(User, SimpleNamespace(id="user-a")),
            schema_application=SimpleNamespace(services=services),
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Entity type with this name already exists"
