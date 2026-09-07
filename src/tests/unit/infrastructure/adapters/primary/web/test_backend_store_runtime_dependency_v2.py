"""Project-bound graph/retrieval runtime resolution through V2 services."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from src.infrastructure.adapters.primary.web import (
    backend_store_authority_v2,
    dependencies,
)
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "headers": [],
            "method": "GET",
            "path": "/api/v1/projects/project-a",
            "path_params": {"project_id": "project-a"},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


def _authority(*, binding_name: str, binding_id: str, service_name: str) -> tuple[Any, Any]:
    result = MagicMock()
    result.first.return_value = ("tenant-a", binding_id)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    service = SimpleNamespace(resolve_backend=AsyncMock(return_value=object()))
    services = SimpleNamespace(graph_service=None, retrieval_service=None)
    setattr(services, service_name, service)
    return SimpleNamespace(db=db, services=services), service


@pytest.mark.parametrize(
    ("dependency", "binding_name", "binding_id", "service_name"),
    (
        (
            dependencies.get_graph_store,
            "graph_store_id",
            "graph-store-a",
            "graph_service",
        ),
        (
            dependencies.get_retrieval_store,
            "retrieval_store_id",
            "retrieval-store-a",
            "retrieval_service",
        ),
    ),
)
async def test_project_bound_runtime_store_uses_v2_application_service(
    dependency: Any,
    binding_name: str,
    binding_id: str,
    service_name: str,
) -> None:
    authority, service = _authority(
        binding_name=binding_name,
        binding_id=binding_id,
        service_name=service_name,
    )

    resolved = await dependency(_request(), backend_store=authority)

    assert resolved is service.resolve_backend.return_value
    authority.db.execute.assert_awaited_once()
    service.resolve_backend.assert_awaited_once_with("tenant-a", binding_id)


@pytest.mark.parametrize(
    ("dependency", "binding_name", "binding_id", "service_name"),
    (
        (
            dependencies.get_graph_store,
            "graph_store_id",
            "graph-store-a",
            "graph_service",
        ),
        (
            dependencies.get_retrieval_store,
            "retrieval_store_id",
            "retrieval-store-a",
            "retrieval_service",
        ),
    ),
)
async def test_project_bound_runtime_store_propagates_v2_resolution_failure(
    dependency: Any,
    binding_name: str,
    binding_id: str,
    service_name: str,
) -> None:
    authority, service = _authority(
        binding_name=binding_name,
        binding_id=binding_id,
        service_name=service_name,
    )
    service.resolve_backend.side_effect = RuntimeError("v2 backend unavailable")

    with pytest.raises(RuntimeError, match="v2 backend unavailable"):
        await dependency(_request(), backend_store=authority)


@pytest.mark.parametrize("binding_id", ("", "__env_neo4j__"))
async def test_default_graph_store_uses_the_pinned_generation(binding_id: str) -> None:
    client = object()
    graph_service = SimpleNamespace(client=client, close=AsyncMock())

    async def graph_factory() -> Any:
        return graph_service

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=graph_factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    authority, service = _authority(
        binding_name="graph_store_id",
        binding_id=binding_id,
        service_name="graph_service",
    )

    assert publication.accepted is True
    async with pin_generation_v2(host):
        assert dependencies.get_graph_service(_request()) is graph_service
        assert dependencies.get_neo4j_client(_request()) is client
        resolved = await dependencies.get_graph_store(_request(), backend_store=authority)

    assert resolved is graph_service
    service.resolve_backend.assert_not_awaited()

    await host.close()

    graph_service.close.assert_awaited_once()


async def test_default_retrieval_store_uses_the_pinned_generation() -> None:
    graph_service = SimpleNamespace(close=AsyncMock())
    retrieval_store = SimpleNamespace(close=AsyncMock())

    async def graph_factory() -> Any:
        return graph_service

    async def retrieval_factory(_graph_runtime: Any) -> Any:
        return retrieval_store

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            graph_runtime_factory=graph_factory,
            retrieval_runtime_factory=retrieval_factory,
        )
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    authority, service = _authority(
        binding_name="retrieval_store_id",
        binding_id="",
        service_name="retrieval_service",
    )

    assert publication.accepted is True
    async with pin_generation_v2(host):
        resolved = await dependencies.get_retrieval_store(_request(), backend_store=authority)

    assert resolved is retrieval_store
    service.resolve_backend.assert_not_awaited()

    await host.close()

    retrieval_store.close.assert_awaited_once()
    graph_service.close.assert_awaited_once()


@pytest.mark.parametrize(
    "dependency",
    (dependencies.get_graph_store, dependencies.get_retrieval_store),
)
def test_runtime_store_dependency_requires_v2_authority(dependency: Any) -> None:
    parameters = signature(dependency).parameters

    assert "backend_store" in parameters
    assert parameters["backend_store"].default.dependency is not None
    assert "db" not in parameters


def test_runtime_store_dependencies_do_not_import_provider_implementations() -> None:
    for name in (
        "SqlGraphStoreRepository",
        "SqlRetrievalStoreRepository",
        "build_default_factory",
        "build_default_retrieval_factory",
        "get_graph_backend_registry",
        "get_retrieval_backend_registry",
    ):
        assert not hasattr(dependencies, name)


async def test_authority_proxy_keeps_canonical_dependency_open_until_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = SimpleNamespace(db=object(), services=object())
    disposed = False

    async def canonical_dependency(**_kwargs: Any) -> Any:
        nonlocal disposed
        try:
            yield expected
        finally:
            disposed = True

    monkeypatch.setattr(
        backend_store_authority_v2,
        "backend_store_authority_dependency_v2",
        canonical_dependency,
    )
    proxy = dependencies._backend_store_authority_dependency_proxy_v2(
        request=_request(),
        current_user=SimpleNamespace(id="user-a"),
        db=SimpleNamespace(),
    )

    assert await anext(proxy) is expected
    assert disposed is False

    await proxy.aclose()

    assert disposed is True
