"""Production V2 ownership tests for the builtin genes HTTP row."""

from __future__ import annotations

import inspect
from collections import Counter
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers.genes import router as legacy_genes_router
from src.infrastructure.plugins.v2 import builtin_genes_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    RouteTableBuilderV2,
    install_route_definitions_v2,
)
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_INJECT_V2

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.infrastructure.plugins.v2.runtime import ContextV2

pytestmark = pytest.mark.unit

_PREFIX = "/api/v1/genes"
type ExpectedRoute = tuple[str, str, str]
type DependencySignature = tuple[
    str | None,
    bool,
    tuple[str, ...],
    tuple[str, ...],
    tuple[Any, ...],
]

_EXPECTED_ROUTES: tuple[ExpectedRoute, ...] = (
    ("POST", "/", "create_gene"),
    ("GET", "/", "list_genes"),
    ("PUT", "/{gene_id}", "update_gene"),
    ("DELETE", "/{gene_id}", "delete_gene"),
    ("POST", "/{gene_id}/publish", "publish_gene"),
    ("POST", "/{gene_id}/unpublish", "unpublish_gene"),
    ("POST", "/genomes", "create_genome"),
    ("GET", "/genomes", "list_genomes"),
    ("GET", "/genomes/{genome_id}", "get_genome"),
    ("PUT", "/genomes/{genome_id}", "update_genome"),
    ("DELETE", "/genomes/{genome_id}", "delete_genome"),
    ("POST", "/genomes/{genome_id}/publish", "publish_genome"),
    ("POST", "/genomes/{genome_id}/unpublish", "unpublish_genome"),
    ("POST", "/instances/{instance_id}/install", "install_gene"),
    (
        "POST",
        "/instances/{instance_id}/genomes/{genome_id}/install",
        "install_genome",
    ),
    (
        "DELETE",
        "/instances/{instance_id}/genes/{instance_gene_id}",
        "uninstall_gene",
    ),
    ("GET", "/instances/{instance_id}/genes", "list_instance_genes"),
    (
        "GET",
        "/instances/{instance_id}/genes/{instance_gene_id}",
        "get_instance_gene",
    ),
    ("POST", "/{gene_id}/ratings", "rate_gene"),
    ("GET", "/{gene_id}/ratings", "list_gene_ratings"),
    ("GET", "/genomes/{genome_id}/ratings", "list_genome_ratings"),
    ("POST", "/genomes/{genome_id}/ratings", "rate_genome"),
    ("GET", "/evolution", "list_evolution_events"),
    ("POST", "/evolution", "create_evolution_event"),
    ("GET", "/evolution/{event_id}", "get_evolution_event"),
    ("GET", "/{gene_id}", "get_gene"),
    ("GET", "/{gene_id}/reviews", "list_gene_reviews"),
    ("POST", "/{gene_id}/reviews", "create_gene_review"),
    ("DELETE", "/{gene_id}/reviews/{review_id}", "delete_gene_review"),
)

_STATIC_GET_PATHS = (
    "/genomes",
    "/genomes/{genome_id}",
    "/instances/{instance_id}/genes",
    "/instances/{instance_id}/genes/{instance_gene_id}",
    "/genomes/{genome_id}/ratings",
    "/evolution",
    "/evolution/{event_id}",
)


def _route_signature(definition: RouteDefinitionV2) -> ExpectedRoute:
    return (
        definition.methods[0],
        definition.path.removeprefix(_PREFIX),
        definition.name,
    )


def _callable_id(value: object | None) -> str | None:
    if value is None:
        return None
    return f"{getattr(value, '__module__', '?')}.{getattr(value, '__qualname__', repr(value))}"


def _dependant_signature(dependant: Dependant) -> DependencySignature:
    return (
        _callable_id(dependant.call),
        dependant.use_cache,
        tuple(dependant.own_oauth_scopes or ()),
        tuple(dependant.parent_oauth_scopes or ()),
        tuple(_dependant_signature(child) for child in dependant.dependencies),
    )


def _walk_dependencies(dependant: Dependant) -> tuple[Dependant, ...]:
    dependencies: list[Dependant] = []
    for child in dependant.dependencies:
        dependencies.append(child)
        dependencies.extend(_walk_dependencies(child))
    return tuple(dependencies)


def _dependency_counter(app: FastAPI, *, recursive: bool) -> Counter[str]:
    calls: list[str] = []
    for route in app.router.routes:
        if not isinstance(route, APIRoute):
            continue
        dependencies = (
            _walk_dependencies(route.dependant)
            if recursive
            else tuple(route.dependant.dependencies)
        )
        calls.extend(
            getattr(dependency.call, "__name__", repr(dependency.call))
            for dependency in dependencies
        )
    return Counter(calls)


def _dependency_signatures(app: FastAPI) -> tuple[tuple[str, str, DependencySignature], ...]:
    return tuple(
        (route.path, next(iter(route.methods)), _dependant_signature(route.dependant))
        for route in app.router.routes
        if isinstance(route, APIRoute)
    )


def _route_map(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    return {
        (next(iter(route.methods)), route.path): route
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }


def _legacy_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(legacy_genes_router)
    return app


def _claimed_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_route_definitions_v2(app, subject.genes_route_definitions_v2())
    return app


class _RecordingBuilder(RouteTableBuilderV2):
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.fail_after = fail_after
        self.registered: list[str] = []
        self.disposed: list[str] = []

    def contribute(
        self,
        definition: RouteDefinitionV2,
    ) -> Callable[[], Awaitable[None]]:
        if self.fail_after is not None and len(self.registered) == self.fail_after:
            raise RuntimeError("planned contribution failure")
        self.registered.append(definition.name)

        async def dispose() -> None:
            self.disposed.append(definition.name)

        return dispose


class _FakeContext:
    def __init__(self, builder: RouteTableBuilderV2, *, teardown: bool) -> None:
        self.builder = builder
        self.teardown = teardown
        self.required_services: list[str] = []
        self.effect_labels: list[str] = []

    def require(self, service: str) -> object:
        self.required_services.append(service)
        return self.builder

    async def effect(
        self,
        setup: Callable[[], Awaitable[object]],
        *,
        label: str,
    ) -> None:
        self.effect_labels.append(label)
        result = await setup()
        if self.teardown:
            disposers = cast("tuple[Callable[[], Awaitable[None]], ...]", result)
            for dispose in reversed(disposers):
                await dispose()


def test_genes_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.genes_route_definitions_v2()
    legacy = _route_map(_legacy_app())
    claimed = _route_map(_claimed_app())

    assert len(definitions) == 29
    assert tuple(_route_signature(definition) for definition in definitions) == _EXPECTED_ROUTES
    assert len(legacy) == len(claimed) == len(definitions)
    for definition in definitions:
        key = definition.methods[0], definition.path
        legacy_route = legacy[key]
        claimed_route = claimed[key]
        assert definition.endpoint is legacy_route.endpoint
        assert definition.response_model == legacy_route.response_model
        assert definition.status_code == legacy_route.status_code
        assert definition.tags == tuple(legacy_route.tags)
        assert definition.summary == legacy_route.summary
        assert definition.deprecated == legacy_route.deprecated
        assert definition.include_in_schema == legacy_route.include_in_schema
        assert claimed_route.endpoint is legacy_route.endpoint
        assert claimed_route.response_model == legacy_route.response_model
        assert claimed_route.status_code == legacy_route.status_code
        assert claimed_route.tags == legacy_route.tags
        assert claimed_route.summary == legacy_route.summary
        assert claimed_route.description == legacy_route.description
        assert claimed_route.deprecated == legacy_route.deprecated
        assert claimed_route.include_in_schema == legacy_route.include_in_schema
    assert Counter(definition.methods[0] for definition in definitions) == {
        "DELETE": 4,
        "GET": 11,
        "POST": 12,
        "PUT": 2,
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.GENES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"genes"}
    assert {definition.tags for definition in definitions} == {("Genes",)}
    assert {
        definition.name: definition.summary
        for definition in definitions
        if definition.summary is not None
    } == {
        "create_gene_review": "Create gene review",
        "delete_gene_review": "Delete gene review",
        "list_gene_reviews": "List gene reviews",
    }
    assert all(definition.deprecated is None for definition in definitions)
    assert all(definition.include_in_schema for definition in definitions)
    source = inspect.getsource(subject)
    assert ".router.routes" not in source
    assert "legacy_genes_router" not in source
    assert "genes.router" not in source


def test_genes_row_preserves_static_get_order_openapi_and_recursive_dependencies() -> None:
    definitions = subject.genes_route_definitions_v2()
    generic_get_index = next(
        index
        for index, definition in enumerate(definitions)
        if definition.methods == ("GET",) and definition.path == f"{_PREFIX}/{{gene_id}}"
    )
    for path in _STATIC_GET_PATHS:
        static_index = next(
            index
            for index, definition in enumerate(definitions)
            if definition.methods == ("GET",) and definition.path == f"{_PREFIX}{path}"
        )
        assert static_index < generic_get_index

    descriptor = PluginGenerationDescriptorV2(
        profile_id="genes-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=definitions,
    )
    legacy_app = _legacy_app()
    claimed_app = _claimed_app()

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            () if definition.methods == ("WEBSOCKET",) else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert _dependency_signatures(claimed_app) == _dependency_signatures(legacy_app)
    assert _dependency_counter(claimed_app, recursive=False) == Counter(
        {
            "gene_admin_application_authority_dependency_v2": 14,
            "gene_application_authority_dependency_v2": 15,
        }
    )
    assert _dependency_counter(claimed_app, recursive=True) == Counter(
        {
            "gene_admin_application_authority_dependency_v2": 14,
            "gene_application_authority_dependency_v2": 15,
            "_get_selected_gene_admin_tenant_id": 14,
            "_get_selected_gene_tenant_id": 15,
            "get_api_key_from_header": 87,
            "get_current_user": 87,
            "get_current_user_tenant": 29,
            "get_db": 261,
            "verify_api_key_dependency": 87,
        }
    )
    assert claimed.v2_owned_row_ids == ("genes",)


def test_genes_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_genes_http_routes_definition_v2()

    assert definition.module_ref == subject.GENES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_genes_route_effect_teardown_disposes_all_contributions_in_lifo_order() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)
    definition = subject.builtin_genes_http_routes_definition_v2()

    await definition.apply(cast("ContextV2", context), {})

    expected = [name for _method, _path, name in _EXPECTED_ROUTES]
    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.GENES_HTTP_ROUTES_ENTRY_V2]


async def test_genes_route_partial_setup_disposes_contributions_in_lifo_order() -> None:
    builder = _RecordingBuilder(fail_after=4)
    context = _FakeContext(builder, teardown=False)
    definition = subject.builtin_genes_http_routes_definition_v2()

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await definition.apply(cast("ContextV2", context), {})

    assert builder.registered == [
        "create_gene",
        "list_genes",
        "update_gene",
        "delete_gene",
    ]
    assert builder.disposed == list(reversed(builder.registered))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.GENES_HTTP_ROUTES_ENTRY_V2]
