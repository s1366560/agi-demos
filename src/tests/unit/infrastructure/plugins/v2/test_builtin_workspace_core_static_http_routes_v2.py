"""Production V2 ownership tests for the Workspace Core static HTTP row."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.workspace_core_routes import (
    WorkspaceCoreProxyRoute,
    register_workspace_core_static_routes,
)
from src.infrastructure.plugins.v2 import builtin_workspace_core_static_http_routes as subject
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


def _route_map(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    return {
        (method, route.path): route
        for route in app.router.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods or ())
    }


def _legacy_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    register_workspace_core_static_routes(app)
    return app


def _claimed_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_route_definitions_v2(app, subject.workspace_core_static_route_definitions_v2())
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


def test_workspace_core_static_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.workspace_core_static_route_definitions_v2()
    legacy = _route_map(_legacy_app())
    claimed = _route_map(_claimed_app())

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        ("/api/v1/workspace-context", ("GET",), "get_workspace_context"),
        ("/api/v1/workspace-context/switch", ("POST",), "switch_workspace_context"),
        (
            "/api/v1/llm-providers/routing-policy",
            ("GET",),
            "get_legacy_workspace_routing_policy",
        ),
        (
            "/api/v1/llm-providers/routing-policy",
            ("PUT",),
            "put_legacy_workspace_routing_policy",
        ),
    )
    assert len(legacy) == len(claimed) == len(definitions) == 4
    for definition in definitions:
        key = definition.methods[0], definition.path
        legacy_route = legacy[key]
        claimed_route = claimed[key]
        assert claimed_route.response_model == legacy_route.response_model
        assert claimed_route.tags == legacy_route.tags
        assert claimed_route.description == legacy_route.description
        if definition.name in {"get_workspace_context", "switch_workspace_context"}:
            assert definition.route_class_override is None
            assert not isinstance(claimed_route, WorkspaceCoreProxyRoute)
            assert claimed_route.endpoint is definition.endpoint
        else:
            assert definition.route_class_override is WorkspaceCoreProxyRoute
            assert isinstance(claimed_route, WorkspaceCoreProxyRoute)
            assert claimed_route.endpoint.__module__ == legacy_route.endpoint.__module__
            assert claimed_route.endpoint.__name__ == legacy_route.endpoint.__name__
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.WORKSPACE_CORE_STATIC_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "workspace-core-static"
    }


def test_workspace_core_static_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="workspace-core-static-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.workspace_core_static_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            () if definition.methods == ("WEBSOCKET",) else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("workspace-core-static",)


def test_workspace_core_static_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_workspace_core_static_http_routes_definition_v2()

    assert definition.module_ref == subject.WORKSPACE_CORE_STATIC_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_workspace_core_static_route_effect_teardown_is_lifo() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)

    await subject.builtin_workspace_core_static_http_routes_definition_v2().apply(
        cast("ContextV2", context),
        {},
    )

    assert builder.registered == [
        "get_workspace_context",
        "switch_workspace_context",
        "get_legacy_workspace_routing_policy",
        "put_legacy_workspace_routing_policy",
    ]
    assert builder.disposed == list(reversed(builder.registered))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.WORKSPACE_CORE_STATIC_HTTP_ROUTES_ENTRY_V2]


async def test_workspace_core_static_route_partial_setup_cleans_up() -> None:
    builder = _RecordingBuilder(fail_after=2)
    context = _FakeContext(builder, teardown=False)

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await subject.builtin_workspace_core_static_http_routes_definition_v2().apply(
            cast("ContextV2", context),
            {},
        )

    assert builder.registered == ["get_workspace_context", "switch_workspace_context"]
    assert builder.disposed == list(reversed(builder.registered))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.WORKSPACE_CORE_STATIC_HTTP_ROUTES_ENTRY_V2]
