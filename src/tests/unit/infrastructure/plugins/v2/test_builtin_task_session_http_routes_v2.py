"""Production V2 ownership tests for the builtin task-session HTTP row."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.workspace_core_task_sessions import (
    router as legacy_task_session_router,
)
from src.infrastructure.plugins.v2 import builtin_task_session_http_routes as subject
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

_PREFIX = "/api/v1/tenants/{tenant_id}/projects/{project_id}/task-sessions"


def _route_map(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    return {
        (next(iter(route.methods)), route.path): route
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }


def _legacy_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(legacy_task_session_router)
    return app


def _claimed_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_route_definitions_v2(app, subject.task_session_route_definitions_v2())
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


def test_task_session_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.task_session_route_definitions_v2()
    legacy = _route_map(_legacy_app())
    claimed = _route_map(_claimed_app())

    assert tuple(
        (definition.path, definition.methods, definition.name, definition.response_model)
        for definition in definitions
    ) == (
        (
            f"{_PREFIX}/capabilities",
            ("GET",),
            "avernet_task_session_capabilities",
            dict[str, Any],
        ),
        (f"{_PREFIX}", ("POST",), "create_avernet_task_session", None),
    )
    assert len(legacy) == len(claimed) == len(definitions) == 2
    for definition in definitions:
        key = definition.methods[0], definition.path
        legacy_route = legacy[key]
        claimed_route = claimed[key]
        assert definition.endpoint is legacy_route.endpoint
        assert definition.response_model == legacy_route.response_model
        assert definition.tags == tuple(legacy_route.tags)
        assert claimed_route.endpoint is legacy_route.endpoint
        assert claimed_route.response_model == legacy_route.response_model
        assert claimed_route.tags == legacy_route.tags
        assert claimed_route.description == legacy_route.description
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TASK_SESSION_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"task-session"}


def test_task_session_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="task-session-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.task_session_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("task-session",)


def test_task_session_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_task_session_http_routes_definition_v2()

    assert definition.module_ref == subject.TASK_SESSION_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_task_session_route_effect_teardown_is_lifo() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)

    await subject.builtin_task_session_http_routes_definition_v2().apply(
        cast("ContextV2", context),
        {},
    )

    assert builder.registered == [
        "avernet_task_session_capabilities",
        "create_avernet_task_session",
    ]
    assert builder.disposed == list(reversed(builder.registered))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.TASK_SESSION_HTTP_ROUTES_ENTRY_V2]


async def test_task_session_route_partial_setup_cleans_up() -> None:
    builder = _RecordingBuilder(fail_after=1)
    context = _FakeContext(builder, teardown=False)

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await subject.builtin_task_session_http_routes_definition_v2().apply(
            cast("ContextV2", context),
            {},
        )

    assert builder.registered == ["avernet_task_session_capabilities"]
    assert builder.disposed == ["avernet_task_session_capabilities"]
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.TASK_SESSION_HTTP_ROUTES_ENTRY_V2]
