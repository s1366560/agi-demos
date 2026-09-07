"""Request-lifetime coverage for the graph V2 application authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.infrastructure.adapters.primary.web.graph_application_authority_v2 import (
    GraphApplicationAuthorityV2,
    graph_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import graph
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
_GRAPH_ENDPOINTS = (
    graph.list_communities,
    graph.list_entities,
    graph.get_entity_types,
    graph.get_entity,
    graph.get_entity_relationships,
    graph.get_graph,
    graph.get_subgraph,
    graph.get_community,
    graph.get_community_members,
    graph.rebuild_communities,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "GET",
            "path": "/api/v1/graph/entities/",
            "path_params": {},
            "query_string": b"tenant_id=tenant-a&project_id=project-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize("endpoint", _GRAPH_ENDPOINTS)
def test_graph_routes_require_v2_application_authority(endpoint: Any) -> None:
    parameters = signature(endpoint).parameters
    parameter = parameters["graph_application"]

    assert parameter.default.dependency is graph_application_authority_dependency_v2
    assert parameter.annotation in {"GraphApplicationAuthorityV2", GraphApplicationAuthorityV2}
    assert "db" not in parameters
    assert "graph_store" not in parameters


def test_graph_routes_remove_static_graph_dependencies() -> None:
    assert "get_db" not in vars(graph)
    assert "get_graph_store" not in vars(graph)


async def test_graph_unavailable_preserves_http_503_contract() -> None:
    authority = SimpleNamespace(
        db=SimpleNamespace(),
        services=SimpleNamespace(graph_store=None),
    )

    with pytest.raises(HTTPException) as error:
        await graph.list_entities(
            current_user=cast(User, SimpleNamespace(is_superuser=True)),
            graph_application=authority,
        )

    assert error.value.status_code == 503
    assert error.value.detail == "Graph backend not available"


async def test_authority_uses_pinned_generation_and_disposes_after_handler() -> None:
    graph_store = cast(GraphStorePort, object())

    async def graph_factory() -> GraphStorePort:
        return graph_store

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=graph_factory)
    )
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=61,
        version=61,
    )
    assert publication.accepted is True
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = graph_application_authority_dependency_v2(
                request=request,
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 61
            assert authority.operation.context.scope.kind is ScopeKindV2.PROJECT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.db is db
            assert authority.services.graph_store is graph_store
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/graph/entities/",
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
        "src.infrastructure.adapters.primary.web.graph_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = graph_application_authority_dependency_v2(
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
