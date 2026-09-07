"""Request-lifetime coverage for graph/retrieval store V2 authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.backend_store_authority_v2 import (
    BackendStoreAuthorityV2,
    backend_store_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import graph_stores, projects, retrieval_stores
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
    graph_stores.list_store_types,
    graph_stores.test_store_raw,
    graph_stores.create_store,
    graph_stores.list_stores,
    graph_stores.get_store,
    graph_stores.update_store,
    graph_stores.delete_store,
    graph_stores.test_store_by_id,
)
_RETRIEVAL_ENDPOINTS = (
    retrieval_stores.list_store_types,
    retrieval_stores.test_store_raw,
    retrieval_stores.create_store,
    retrieval_stores.list_stores,
    retrieval_stores.get_store,
    retrieval_stores.update_store,
    retrieval_stores.delete_store,
    retrieval_stores.test_store_by_id,
)
_PROJECT_BACKEND_ENDPOINTS = (
    projects.create_project,
    projects.list_projects,
    projects.get_project,
    projects.update_project,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "GET",
            "path": "/api/v1/graph-stores",
            "path_params": {},
            "query_string": b"tenant_id=tenant-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize("endpoint", (*_GRAPH_ENDPOINTS, *_RETRIEVAL_ENDPOINTS))
def test_store_management_routes_require_v2_authority(endpoint: Any) -> None:
    parameter = signature(endpoint).parameters["backend_store"]

    assert parameter.default.dependency is backend_store_authority_dependency_v2
    assert parameter.annotation in {"BackendStoreAuthorityV2", BackendStoreAuthorityV2}
    assert "db" not in signature(endpoint).parameters


def test_store_management_legacy_service_accessors_are_removed() -> None:
    assert "_service" not in vars(graph_stores)
    assert "_service" not in vars(retrieval_stores)


@pytest.mark.parametrize("endpoint", _PROJECT_BACKEND_ENDPOINTS)
def test_project_backend_routes_require_v2_authority(endpoint: Any) -> None:
    parameters = signature(endpoint).parameters
    parameter = parameters["backend_store"]

    assert parameter.default.dependency is backend_store_authority_dependency_v2
    assert parameter.annotation in {"BackendStoreAuthorityV2", BackendStoreAuthorityV2}
    assert "db" not in parameters


def test_project_backend_static_service_builder_is_removed() -> None:
    assert "_build_backend_services" not in vars(projects)


@pytest.mark.parametrize(
    ("normalizer", "store_id"),
    (
        (projects._normalize_graph_store_binding, "graph-store-a"),
        (projects._normalize_retrieval_store_binding, "retrieval-store-a"),
    ),
)
async def test_project_binding_normalizers_use_the_v2_service(
    normalizer: Any,
    store_id: str,
) -> None:
    service = SimpleNamespace(get_store=AsyncMock(return_value=object()))

    normalized = await normalizer(
        service,
        tenant_id="tenant-a",
        store_id=store_id,
    )

    assert normalized == store_id
    service.get_store.assert_awaited_once_with("tenant-a", store_id)


@pytest.mark.parametrize(
    ("endpoint", "service_name", "expected"),
    (
        (graph_stores.list_store_types, "graph_service", [{"type": "graph-v2"}]),
        (
            retrieval_stores.list_store_types,
            "retrieval_service",
            [{"type": "retrieval-v2"}],
        ),
    ),
)
async def test_store_type_routes_read_the_v2_authority_service(
    endpoint: Any,
    service_name: str,
    expected: list[dict[str, str]],
) -> None:
    selected_service = SimpleNamespace(list_store_types=MagicMock(return_value=expected))
    services = SimpleNamespace(
        graph_service=selected_service,
        retrieval_service=selected_service,
    )

    response = await endpoint(
        current_user=cast(User, SimpleNamespace(id="user-a")),
        backend_store=SimpleNamespace(services=services),
    )

    assert response == {"success": True, "data": expected}
    selected_service.list_store_types.assert_called_once_with()
    assert getattr(services, service_name) is selected_service


async def test_authority_uses_pinned_generation_and_disposes_after_handler() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=10,
        version=10,
    )
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = backend_store_authority_dependency_v2(
                request=request,
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 10
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.db is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/graph-stores",
            }
            assert getattr(authority.services.graph_service._repo, "_session", None) is db
            assert getattr(authority.services.retrieval_service._repo, "_session", None) is db
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
        "src.infrastructure.adapters.primary.web.backend_store_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = backend_store_authority_dependency_v2(
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
