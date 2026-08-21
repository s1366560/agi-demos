"""Request-lifetime coverage for the enhanced-search V2 authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.retrieval_store_port import RetrievalStorePort
from src.infrastructure.adapters.primary.web.routers import enhanced_search
from src.infrastructure.adapters.primary.web.search_application_authority_v2 import (
    SearchApplicationAuthorityV2,
    search_application_authority_dependency_v2,
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
_SEARCH_ENDPOINTS = (
    enhanced_search.search_advanced,
    enhanced_search.search_by_graph_traversal,
    enhanced_search.search_by_community,
    enhanced_search.search_temporal,
    enhanced_search.search_with_facets,
    enhanced_search.get_search_capabilities,
    enhanced_search.memory_search,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "POST",
            "path": "/api/v1/search-enhanced/advanced",
            "path_params": {},
            "query_string": b"tenant_id=tenant-a&project_id=project-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize("endpoint", _SEARCH_ENDPOINTS)
def test_search_routes_require_v2_application_authority(endpoint: Any) -> None:
    parameters = signature(endpoint).parameters
    parameter = parameters["search_application"]

    assert parameter.default.dependency is search_application_authority_dependency_v2
    assert parameter.annotation in {"SearchApplicationAuthorityV2", SearchApplicationAuthorityV2}
    assert "db" not in parameters
    assert "graph_service" not in parameters
    assert "graph_store" not in parameters
    assert "retrieval_store" not in parameters


def test_search_routes_remove_static_store_dependencies() -> None:
    for name in ("get_db", "get_graph_service", "get_graph_store", "get_retrieval_store"):
        assert name not in vars(enhanced_search)


async def test_memory_search_reads_retrieval_from_v2_authority() -> None:
    retrieval_store = SimpleNamespace(
        hybrid_search=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id="memory-a",
                    metadata={"title": "Memory A"},
                    source_id="memory-a",
                    content="Generation-owned retrieval result",
                    score=0.9,
                    created_at=None,
                    source_type="memory",
                    category="fact",
                )
            ]
        )
    )
    graph_service = SimpleNamespace(search=AsyncMock())
    authority = SimpleNamespace(
        db=SimpleNamespace(),
        services=SimpleNamespace(
            graph_service=graph_service,
            retrieval_store=retrieval_store,
        ),
    )

    response = await enhanced_search.memory_search(
        {"query": "generation", "project_id": "project-a", "limit": 1},
        current_user=cast(User, SimpleNamespace(id="user-a")),
        search_application=authority,
    )

    assert response["results"][0]["uuid"] == "memory-a"
    retrieval_store.hybrid_search.assert_awaited_once_with(
        query="generation",
        project_id="project-a",
        limit=1,
    )
    graph_service.search.assert_not_awaited()


async def test_authority_uses_pinned_generation_and_disposes_after_handler() -> None:
    graph_service = cast(GraphStorePort, object())
    retrieval_store = cast(RetrievalStorePort, object())

    async def graph_factory() -> GraphStorePort:
        return graph_service

    async def retrieval_factory(_graph_runtime: object) -> RetrievalStorePort:
        return retrieval_store

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            graph_runtime_factory=graph_factory,
            retrieval_runtime_factory=retrieval_factory,
        )
    )
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=41,
        version=41,
    )
    assert publication.accepted is True
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = search_application_authority_dependency_v2(
                request=request,
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 41
            assert authority.operation.context.scope.kind is ScopeKindV2.PROJECT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.db is db
            assert authority.services.graph_service is graph_service
            assert authority.services.retrieval_store is retrieval_store
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/search-enhanced/advanced",
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
        "src.infrastructure.adapters.primary.web.search_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = search_application_authority_dependency_v2(
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
