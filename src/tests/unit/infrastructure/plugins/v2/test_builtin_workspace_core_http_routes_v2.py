"""Production V2 ownership tests for the complete Workspace Core HTTP row."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.workspace_core_routes import (
    register_workspace_core_routes,
)
from src.infrastructure.plugins.v2 import builtin_workspace_core_http_routes as subject
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

_SOURCE_MODULES = {
    "blackboard",
    "cyber_genes",
    "cyber_objectives",
    "topology",
    "workspace_agent_policy",
    "workspace_autonomy",
    "workspace_chat",
    "workspace_collaboration_mutations",
    "workspace_plans",
    "workspace_tasks",
    "workspaces",
}


def _route_map(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    return {
        (method, route.path): route
        for route in app.router.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods or ())
    }


def _legacy_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    register_workspace_core_routes(app)
    return app


def _claimed_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_route_definitions_v2(app, subject.workspace_core_route_definitions_v2())
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


def test_workspace_core_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.workspace_core_route_definitions_v2()
    legacy = _route_map(_legacy_app())
    claimed = _route_map(_claimed_app())

    assert len(legacy) == len(claimed) == len(definitions) == 88
    assert {
        definition.endpoint.__module__.rsplit(".", maxsplit=1)[-1] for definition in definitions
    } == _SOURCE_MODULES
    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == set(legacy)
    for definition in definitions:
        key = definition.methods[0], definition.path
        legacy_route = legacy[key]
        claimed_route = claimed[key]
        assert claimed_route.endpoint.__module__ == legacy_route.endpoint.__module__
        assert claimed_route.endpoint.__name__ == legacy_route.endpoint.__name__
        assert claimed_route.response_model == legacy_route.response_model
        assert claimed_route.tags == legacy_route.tags
        assert claimed_route.description == legacy_route.description
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.WORKSPACE_CORE_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"workspace-core"}


def test_workspace_core_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="workspace-core-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.workspace_core_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("workspace-core",)


def test_workspace_core_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_workspace_core_http_routes_definition_v2()

    assert definition.module_ref == subject.WORKSPACE_CORE_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_workspace_core_route_effect_teardown_is_lifo() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)
    expected = [definition.name for definition in subject.workspace_core_route_definitions_v2()]

    await subject.builtin_workspace_core_http_routes_definition_v2().apply(
        cast("ContextV2", context),
        {},
    )

    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.WORKSPACE_CORE_HTTP_ROUTES_ENTRY_V2]


async def test_workspace_core_route_partial_setup_cleans_up() -> None:
    builder = _RecordingBuilder(fail_after=3)
    context = _FakeContext(builder, teardown=False)
    expected = [definition.name for definition in subject.workspace_core_route_definitions_v2()[:3]]

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await subject.builtin_workspace_core_http_routes_definition_v2().apply(
            cast("ContextV2", context),
            {},
        )

    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.WORKSPACE_CORE_HTTP_ROUTES_ENTRY_V2]
