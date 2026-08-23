"""Production V2 ownership tests for the builtin channels HTTP row."""

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
from src.infrastructure.adapters.primary.web.routers.channels import (
    router as legacy_channels_router,
)
from src.infrastructure.plugins.v2 import builtin_channels_http_routes as subject
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

_PREFIX = "/api/v1/channels"
type ExpectedRoute = tuple[str, str, str]
type DependencySignature = tuple[
    str | None,
    bool,
    tuple[str, ...],
    tuple[str, ...],
    tuple[Any, ...],
]

_EXPECTED_ROUTES: tuple[ExpectedRoute, ...] = (
    ("GET", "/projects/{project_id}/plugins", "list_project_plugins"),
    ("GET", "/tenants/{tenant_id}/plugins", "list_tenant_plugins"),
    (
        "GET",
        "/tenants/{tenant_id}/plugins/{plugin_name}/config-schema",
        "get_tenant_plugin_config_schema",
    ),
    (
        "GET",
        "/tenants/{tenant_id}/plugins/{plugin_name}/config",
        "get_tenant_plugin_config",
    ),
    (
        "PUT",
        "/tenants/{tenant_id}/plugins/{plugin_name}/config",
        "update_tenant_plugin_config",
    ),
    (
        "GET",
        "/tenants/{tenant_id}/plugins/channel-catalog",
        "list_tenant_channel_plugin_catalog",
    ),
    (
        "GET",
        "/tenants/{tenant_id}/plugins/channel-catalog/{channel_type}/schema",
        "get_tenant_channel_plugin_schema",
    ),
    ("POST", "/tenants/{tenant_id}/plugins/install", "install_tenant_plugin"),
    (
        "POST",
        "/tenants/{tenant_id}/plugins/{plugin_name}/enable",
        "enable_tenant_plugin",
    ),
    (
        "POST",
        "/tenants/{tenant_id}/plugins/{plugin_name}/disable",
        "disable_tenant_plugin",
    ),
    (
        "POST",
        "/tenants/{tenant_id}/plugins/{plugin_name}/uninstall",
        "uninstall_tenant_plugin",
    ),
    ("POST", "/tenants/{tenant_id}/plugins/reload", "reload_tenant_plugins"),
    (
        "GET",
        "/projects/{project_id}/plugins/channel-catalog",
        "list_project_channel_plugin_catalog",
    ),
    (
        "GET",
        "/projects/{project_id}/plugins/channel-catalog/{channel_type}/schema",
        "get_project_channel_plugin_schema",
    ),
    ("POST", "/projects/{project_id}/plugins/install", "install_project_plugin"),
    (
        "POST",
        "/projects/{project_id}/plugins/{plugin_name}/enable",
        "enable_project_plugin",
    ),
    (
        "POST",
        "/projects/{project_id}/plugins/{plugin_name}/disable",
        "disable_project_plugin",
    ),
    (
        "POST",
        "/projects/{project_id}/plugins/{plugin_name}/uninstall",
        "uninstall_project_plugin",
    ),
    ("POST", "/projects/{project_id}/plugins/reload", "reload_project_plugins"),
    ("POST", "/projects/{project_id}/configs", "create_config"),
    ("GET", "/projects/{project_id}/configs", "list_configs"),
    ("GET", "/configs/{config_id}", "get_config"),
    ("PUT", "/configs/{config_id}", "update_config"),
    ("DELETE", "/configs/{config_id}", "delete_config"),
    ("POST", "/configs/{config_id}/test", "test_config"),
    (
        "GET",
        "/projects/{project_id}/observability/summary",
        "get_project_channel_observability_summary",
    ),
    (
        "GET",
        "/projects/{project_id}/observability/outbox",
        "list_project_channel_outbox",
    ),
    (
        "GET",
        "/projects/{project_id}/observability/session-bindings",
        "list_project_channel_session_bindings",
    ),
    ("GET", "/configs/{config_id}/status", "get_connection_status"),
    ("GET", "/status", "list_all_connection_status"),
    ("POST", "/conversations/{conversation_id}/push", "push_message_to_channel"),
)

_PUSH_DESCRIPTION = "Send an agent-initiated message to the channel bound to a conversation."


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


def _dependency_signatures(app: FastAPI) -> tuple[tuple[str, str, DependencySignature], ...]:
    return tuple(
        (route.path, next(iter(route.methods)), _dependant_signature(route.dependant))
        for route in app.router.routes
        if isinstance(route, APIRoute)
    )


def _legacy_route_map() -> dict[tuple[str, str], APIRoute]:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(legacy_channels_router, prefix="/api/v1")
    return {
        (next(iter(route.methods)), route.path): route
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }


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


def test_channels_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.channels_route_definitions_v2()
    legacy = _legacy_route_map()

    assert len(definitions) == 31
    assert tuple(_route_signature(definition) for definition in definitions) == _EXPECTED_ROUTES
    assert len(legacy) == len(definitions)
    for definition in definitions:
        route = legacy[(definition.methods[0], definition.path)]
        assert definition.endpoint is route.endpoint
        assert definition.response_model == route.response_model
        assert definition.status_code == route.status_code
        assert definition.tags == tuple(route.tags)
        assert definition.summary == route.summary
        assert definition.deprecated == route.deprecated
    assert Counter(definition.methods[0] for definition in definitions) == {
        "DELETE": 1,
        "GET": 15,
        "POST": 13,
        "PUT": 2,
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.CHANNELS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"channels"}
    assert {definition.tags for definition in definitions} == {("channels",)}
    assert {
        definition.name: definition.summary
        for definition in definitions
        if definition.summary is not None
    } == {"push_message_to_channel": "Push message to channel"}
    assert {
        definition.name: definition.description
        for definition in definitions
        if definition.description is not None
    } == {"push_message_to_channel": _PUSH_DESCRIPTION}
    assert all(definition.deprecated is None for definition in definitions)
    assert all(definition.include_in_schema for definition in definitions)
    source = inspect.getsource(subject)
    assert ".router.routes" not in source
    assert "legacy_channels_router" not in source


def test_channels_row_preserves_route_order_openapi_and_recursive_dependencies() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="channels-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.channels_route_definitions_v2(),
    )
    legacy_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    legacy_app.include_router(legacy_channels_router, prefix="/api/v1")
    claimed_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    install_route_definitions_v2(claimed_app, subject.channels_route_definitions_v2())

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert _dependency_signatures(claimed_app) == _dependency_signatures(legacy_app)
    assert claimed.v2_owned_row_ids == ("channels",)


def test_channels_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_channels_http_routes_definition_v2()

    assert definition.module_ref == subject.CHANNELS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")


async def test_channels_route_effect_teardown_disposes_all_contributions_in_lifo_order() -> None:
    builder = _RecordingBuilder()
    context = _FakeContext(builder, teardown=True)
    definition = subject.builtin_channels_http_routes_definition_v2()

    await definition.apply(cast("ContextV2", context), {})

    expected = [name for _method, _path, name in _EXPECTED_ROUTES]
    assert builder.registered == expected
    assert builder.disposed == list(reversed(expected))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.CHANNELS_HTTP_ROUTES_ENTRY_V2]


async def test_channels_route_partial_setup_disposes_contributions_in_lifo_order() -> None:
    builder = _RecordingBuilder(fail_after=3)
    context = _FakeContext(builder, teardown=False)
    definition = subject.builtin_channels_http_routes_definition_v2()

    with pytest.raises(RuntimeError, match="planned contribution failure"):
        await definition.apply(cast("ContextV2", context), {})

    assert builder.registered == [
        "list_project_plugins",
        "list_tenant_plugins",
        "get_tenant_plugin_config_schema",
    ]
    assert builder.disposed == list(reversed(builder.registered))
    assert context.required_services == [ROUTE_TABLE_BUILDER_INJECT_V2]
    assert context.effect_labels == [subject.CHANNELS_HTTP_ROUTES_ENTRY_V2]
