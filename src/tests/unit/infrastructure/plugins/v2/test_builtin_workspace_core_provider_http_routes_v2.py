"""Production V2 ownership tests for the Workspace Core Provider HTTP row."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web.workspace_core_runtime import (
    install_workspace_core_runtime,
)
from src.infrastructure.plugins.v2 import builtin_workspace_core_provider_http_routes as subject
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


def _settings() -> WorkspaceCoreSettings:
    return WorkspaceCoreSettings.model_validate(
        {
            "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
            "WORKSPACE_CORE_SERVICE_TOKEN": "service-token",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "webhook-token",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "event-token",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "registry-token",
        }
    )


def _route_map(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    return {
        (method, route.path): route
        for route in app.router.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods or ())
    }


def _legacy_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_workspace_core_runtime(app, _settings())
    return app


def _claimed_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_route_definitions_v2(
        app,
        subject.workspace_core_provider_route_definitions_v2(),
    )
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


def test_workspace_core_provider_row_is_an_exact_v2_contribution() -> None:
    definitions = subject.workspace_core_provider_route_definitions_v2()
    legacy = _route_map(_legacy_app())
    claimed = _route_map(_claimed_app())

    assert len(legacy) == len(claimed) == len(definitions) == 8
    assert set(claimed) == set(legacy)
    for definition in definitions:
        key = definition.methods[0], definition.path
        assert claimed[key].endpoint is legacy[key].endpoint
        assert claimed[key].include_in_schema is False
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "workspace-core-runtime"
    }


def test_workspace_core_provider_module_uses_generated_contract_binding() -> None:
    definition = subject.builtin_workspace_core_provider_http_routes_definition_v2()

    assert definition.module_ref == subject.WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_workspace_core_provider_route_effect_teardown_is_lifo() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)
    expected = [
        definition.name for definition in subject.workspace_core_provider_route_definitions_v2()
    ]

    await subject.builtin_workspace_core_provider_http_routes_definition_v2().apply(
        cast("ContextV2", context),
        {},
    )

    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.WORKSPACE_CORE_PROVIDER_HTTP_ROUTES_ENTRY_V2]


async def test_workspace_core_provider_route_partial_setup_cleans_up() -> None:
    builder = _RecordingBuilder(fail_after=3)
    context = _FakeContext(builder, teardown=False)
    expected = [
        definition.name for definition in subject.workspace_core_provider_route_definitions_v2()[:3]
    ]

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await subject.builtin_workspace_core_provider_http_routes_definition_v2().apply(
            cast("ContextV2", context),
            {},
        )

    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
