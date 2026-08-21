"""Request-lifetime coverage for the memory application V2 authority."""

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
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.infrastructure.adapters.primary.web.memory_application_authority_v2 import (
    MemoryApplicationAuthorityV2,
    memory_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import memories
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
_MEMORY_ENDPOINTS = (
    memories.extract_entities,
    memories.extract_relationships,
    memories.create_memory,
    memories.list_memories,
    memories.get_memory,
    memories.delete_memory,
    memories.reprocess_memory,
    memories.update_memory,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "POST",
            "path": "/api/v1/memories/",
            "path_params": {},
            "query_string": b"tenant_id=tenant-a&project_id=project-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize("endpoint", _MEMORY_ENDPOINTS)
def test_memory_routes_require_v2_application_authority(endpoint: Any) -> None:
    parameters = signature(endpoint).parameters
    parameter = parameters["memory_application"]

    assert parameter.default.dependency is memory_application_authority_dependency_v2
    assert parameter.annotation in {"MemoryApplicationAuthorityV2", MemoryApplicationAuthorityV2}
    assert "db" not in parameters
    assert "graph_service" not in parameters


def test_memory_routes_remove_static_store_dependencies() -> None:
    assert "get_db" not in vars(memories)
    assert "get_graph_service" not in vars(memories)


async def test_authority_uses_pinned_generation_and_disposes_after_handler() -> None:
    graph_service = cast(GraphStorePort, object())

    async def graph_factory() -> GraphStorePort:
        return graph_service

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=graph_factory)
    )
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=21,
        version=21,
    )
    assert publication.accepted is True
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = memory_application_authority_dependency_v2(
                request=request,
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 21
            assert authority.operation.context.scope.kind is ScopeKindV2.PROJECT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.db is db
            assert authority.services.graph_service is graph_service
            assert getattr(authority.services.memory_repository, "_session", None) is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/memories/",
            }
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


async def test_authority_propagates_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.memory_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = memory_application_authority_dependency_v2(
        request=request,
        current_user=user,
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"
