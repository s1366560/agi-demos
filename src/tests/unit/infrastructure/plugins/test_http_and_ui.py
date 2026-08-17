import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.model.plugins import PluginRuntimeKind, PluginTrust
from src.domain.ports.plugins import (
    HttpAuthorizationMode,
    HttpRouteDefinition,
    UiSlotDefinition,
    UiSlotKind,
)
from src.infrastructure.plugins.http_routes import (
    HttpRouteCapabilityAppAssembler,
    HttpRouteCapabilityRow,
    HttpRouteMountError,
    HttpRouteMountService,
)
from src.infrastructure.plugins.ui_slots import UiSlotRegistrationError, UiSlotRegistry


def _dependency():
    return "authorized"


@pytest.mark.unit
def test_plugin_http_route_mounts_and_unmounts() -> None:
    app = FastAPI()
    service = HttpRouteMountService(app)

    async def handler():
        return {"ok": True}

    dispose = service.mount(
        HttpRouteDefinition(
            plugin_id="example",
            method="GET",
            path="/api/v1/plugins/example/hello",
            permission="plugin.example.read",
            authorization=HttpAuthorizationMode.TENANT_MEMBER,
        ),
        handler,
        auth_dependency=_dependency,
    )
    assert len(service.list_routes()) == 1
    assert TestClient(app).get("/api/v1/plugins/example/hello").json() == {"ok": True}

    dispose()
    assert service.list_routes() == ()


@pytest.mark.unit
def test_plugin_route_requires_scoped_auth_dependency() -> None:
    service = HttpRouteMountService(FastAPI())
    definition = HttpRouteDefinition(
        plugin_id="example",
        method="GET",
        path="/api/v1/plugins/example/hello",
        permission="plugin.example.read",
        authorization=HttpAuthorizationMode.AUTHENTICATED,
    )

    with pytest.raises(HttpRouteMountError, match="unsafe route definition"):
        service.mount(
            definition,
            lambda: None,
            auth_dependency=_dependency,
        )
    with pytest.raises(HttpRouteMountError, match="requires auth dependency"):
        service.mount(
            HttpRouteDefinition(
                plugin_id="example",
                method="GET",
                path="/api/v1/plugins/example/hello",
                permission="plugin.example.read",
                authorization=HttpAuthorizationMode.TENANT_MEMBER,
            ),
            lambda: None,
            auth_dependency=None,
        )


@pytest.mark.unit
def test_http_route_assembler_mounts_and_removes_desired_rows() -> None:
    app = FastAPI()
    service = HttpRouteMountService(app)
    assembler = HttpRouteCapabilityAppAssembler(
        service,
        {HttpAuthorizationMode.TENANT_MEMBER: _dependency},
    )

    async def handler():
        return {"ok": True}

    added, removed = assembler.reconcile(
        [
            HttpRouteCapabilityRow(
                plugin_id="example",
                method="GET",
                path="/api/v1/plugins/example/hello",
                permission="plugin.example.read",
                authorization_mode="tenant_member",
            )
        ],
        {("GET", "/api/v1/plugins/example/hello"): handler},
    )
    assert (added, removed) == (1, 0)

    added, removed = assembler.reconcile([], {})
    assert (added, removed) == (0, 1)
    assert service.list_routes() == ()


@pytest.mark.unit
def test_ui_slots_accept_only_sandboxed_builtin_frontend_modules() -> None:
    registry = UiSlotRegistry()
    definition = UiSlotDefinition(
        plugin_id="builtin-ui",
        slot=UiSlotKind.TOOL_RESULT_RENDERER,
        id="custom-renderer",
        module_ref="builtin:custom-renderer",
        permission="ui.render.custom",
    )

    dispose = registry.register(
        definition,
        trust=PluginTrust.BUILTIN,
        runtime=PluginRuntimeKind.FRONTEND,
    )
    assert registry.list(UiSlotKind.TOOL_RESULT_RENDERER) == (definition,)
    dispose()
    assert registry.list(UiSlotKind.TOOL_RESULT_RENDERER) == ()

    with pytest.raises(UiSlotRegistrationError, match="sandbox"):
        registry.register(
            UiSlotDefinition(
                plugin_id="builtin-ui",
                slot=UiSlotKind.SETTINGS_PAGE,
                id="unsafe",
                module_ref="builtin:unsafe",
                permission="ui.settings",
                sandbox=False,
            ),
            trust=PluginTrust.BUILTIN,
            runtime=PluginRuntimeKind.FRONTEND,
        )
