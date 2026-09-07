"""Restricted route-registration materialization tests for protocol v2."""

from __future__ import annotations

import socket
from typing import Any

import pytest
from fastapi import APIRouter

from src.infrastructure.plugins.v2.route_registration import (
    RouteRegistrationClassificationV2,
    RouteRegistrationSinkV2,
    RouteRegistrationViolationV2,
    inspect_route_registration_callable_v2,
    materialize_route_registration_v2,
)

_DIRECT_GLOBAL_SENTINEL = "unchanged"
_INDIRECT_GLOBAL_SENTINEL = "unchanged"
_NESTED_GLOBAL_SENTINEL = "unchanged"


def _endpoint() -> dict[str, bool]:
    return {"ok": True}


def _router_factory() -> APIRouter:
    router = APIRouter(prefix="/factory")
    router.add_api_route("/status", _endpoint, methods=["GET"], name="factory-status")
    return router


def _direct_global_factory() -> APIRouter:
    global _DIRECT_GLOBAL_SENTINEL
    _DIRECT_GLOBAL_SENTINEL = "mutated"
    return _router_factory()


def _indirect_global_writer() -> None:
    global _INDIRECT_GLOBAL_SENTINEL
    _INDIRECT_GLOBAL_SENTINEL = "mutated"


def _indirect_global_factory() -> APIRouter:
    _indirect_global_writer()
    return _router_factory()


def _nested_global_factory() -> APIRouter:
    def mutate() -> None:
        global _NESTED_GLOBAL_SENTINEL
        _NESTED_GLOBAL_SENTINEL = "mutated"

    mutate()
    return _router_factory()


def _escape_direct_sink_app(app: RouteRegistrationSinkV2) -> None:
    app._app.dependency_overrides[_endpoint] = _endpoint
    app.add_api_route("/escape", _endpoint, methods=["GET"], name="escape")


def _escape_nested_getattr(app: RouteRegistrationSinkV2) -> None:
    getattr(getattr(app, "_app"), "state").value = True  # noqa: B009
    app.add_api_route("/escape", _endpoint, methods=["GET"], name="escape")


def _escape_router_app(app: RouteRegistrationSinkV2) -> None:
    app.router._app.dependency_overrides[_endpoint] = _endpoint
    app.add_api_route("/escape", _endpoint, methods=["GET"], name="escape")


def _escape_route_collection(app: RouteRegistrationSinkV2) -> None:
    app.router.routes._routes.clear()
    app.add_api_route("/escape", _endpoint, methods=["GET"], name="escape")


def _escape_with_object_getattribute(app: RouteRegistrationSinkV2) -> None:
    object.__getattribute__(app, "_app").dependency_overrides[_endpoint] = _endpoint
    app.add_api_route("/escape", _endpoint, methods=["GET"], name="escape")


@pytest.mark.unit
def test_restricted_sink_exposes_only_route_registration_surface() -> None:
    sink = RouteRegistrationSinkV2()
    router = APIRouter()
    router.add_api_route("/ok", _endpoint, methods=["GET"], name="ok")

    sink.include_router(router)
    sink.add_api_route("/direct", _endpoint, methods=["GET"], name="direct")

    assert [route.path for route in sink.router.routes] == ["/ok", "/direct"]
    with pytest.raises(RouteRegistrationViolationV2, match="dependency_overrides"):
        _ = sink.dependency_overrides


@pytest.mark.unit
def test_restricted_wrappers_hide_backing_handles_and_instance_dicts() -> None:
    sink = RouteRegistrationSinkV2()

    with pytest.raises(RouteRegistrationViolationV2, match="_app"):
        _ = sink._app
    with pytest.raises(RouteRegistrationViolationV2, match="__dict__"):
        _ = sink.__dict__
    with pytest.raises(RouteRegistrationViolationV2, match=r"router\._app"):
        _ = sink.router._app
    with pytest.raises(RouteRegistrationViolationV2, match=r"router\.routes\._routes"):
        _ = sink.router.routes._routes
    with pytest.raises(RouteRegistrationViolationV2, match=r"router\.routes\.__dict__"):
        _ = sink.router.routes.__dict__


@pytest.mark.unit
@pytest.mark.parametrize(
    "register",
    [
        _escape_direct_sink_app,
        _escape_nested_getattr,
        _escape_router_app,
        _escape_route_collection,
        _escape_with_object_getattribute,
    ],
)
def test_static_preflight_rejects_backing_handle_escape_before_execution(
    register: Any,
) -> None:
    inspection = inspect_route_registration_callable_v2(register)
    result = materialize_route_registration_v2(kind="helper", target=register)

    assert inspection.forbidden_effect_references
    assert result.classification is RouteRegistrationClassificationV2.HYBRID
    assert result.ordered_signatures == ()
    assert result.openapi_digest is None
    assert "non-route effects forbidden" in result.rejections[0]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("attribute", "call"),
    [
        ("state", False),
        ("middleware", True),
        ("add_middleware", True),
        ("on_event", True),
        ("lifespan", False),
        ("mount", True),
    ],
)
def test_restricted_sink_rejects_non_route_effects(attribute: str, call: bool) -> None:
    sink = RouteRegistrationSinkV2()

    with pytest.raises(RouteRegistrationViolationV2, match=attribute):
        value = getattr(sink, attribute)
        if call:
            value("/forbidden", object())


@pytest.mark.unit
def test_restricted_router_rejects_nested_mount_and_lifespan_access() -> None:
    sink = RouteRegistrationSinkV2()

    with pytest.raises(RouteRegistrationViolationV2, match="router.mount"):
        sink.router.mount("/forbidden", object())
    with pytest.raises(RouteRegistrationViolationV2, match="router.lifespan_context"):
        _ = sink.router.lifespan_context


@pytest.mark.unit
def test_restricted_route_collection_allows_only_typed_append() -> None:
    sink = RouteRegistrationSinkV2()

    with pytest.raises(RouteRegistrationViolationV2, match="router.routes.append"):
        sink.router.routes.append(object())  # type: ignore[arg-type]
    with pytest.raises(RouteRegistrationViolationV2, match="router.routes.clear"):
        sink.router.routes.clear()


@pytest.mark.unit
def test_materializes_router_object_and_factory_without_row_id_policy() -> None:
    router = APIRouter(prefix="/object")
    router.add_api_route("/status", _endpoint, methods=["GET"], name="object-status")

    direct = materialize_route_registration_v2(
        kind="include_router",
        target=router,
        prefix="/api",
    )
    factory = materialize_route_registration_v2(
        kind="include_router",
        target=_router_factory,
        prefix="/api",
    )

    assert direct.classification is RouteRegistrationClassificationV2.ROUTES_ONLY
    assert direct.ordered_signatures[0].path == "/api/object/status"
    assert factory.classification is RouteRegistrationClassificationV2.ROUTES_ONLY
    assert factory.ordered_signatures[0].path == "/api/factory/status"
    assert direct.openapi_digest.startswith("sha256:")
    assert factory.openapi_digest.startswith("sha256:")


@pytest.mark.unit
def test_materializes_route_only_helper() -> None:
    def register(app: RouteRegistrationSinkV2) -> None:
        app.add_api_route("/helper", _endpoint, methods=["POST"], name="helper")

    result = materialize_route_registration_v2(kind="helper", target=register)

    assert result.classification is RouteRegistrationClassificationV2.ROUTES_ONLY
    assert [(item.path, item.name, item.methods) for item in result.ordered_signatures] == [
        ("/helper", "helper", ("POST",))
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("factory", "sentinel_name"),
    [
        (_direct_global_factory, "_DIRECT_GLOBAL_SENTINEL"),
        (_indirect_global_factory, "_INDIRECT_GLOBAL_SENTINEL"),
        (_nested_global_factory, "_NESTED_GLOBAL_SENTINEL"),
    ],
)
def test_recursive_bytecode_scan_blocks_global_writes_before_execution(
    factory: Any,
    sentinel_name: str,
) -> None:
    before = globals()[sentinel_name]

    inspection = inspect_route_registration_callable_v2(factory)
    result = materialize_route_registration_v2(kind="include_router", target=factory)

    assert inspection.global_writes
    assert result.classification is RouteRegistrationClassificationV2.HYBRID
    assert result.ordered_signatures == ()
    assert globals()[sentinel_name] == before == "unchanged"


@pytest.mark.unit
def test_resource_capable_helper_is_rejected_without_calling_external_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden_connect(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)

    def register(app: RouteRegistrationSinkV2) -> None:
        socket.create_connection(("127.0.0.1", 1))
        app.add_api_route("/never", _endpoint, methods=["GET"], name="never")

    result = materialize_route_registration_v2(kind="helper", target=register)

    assert result.classification is RouteRegistrationClassificationV2.HYBRID
    assert result.ordered_signatures == ()
    assert called is False
    assert any("socket" in reason for reason in result.rejections)


@pytest.mark.unit
def test_nested_resource_call_is_rejected_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden_connect(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)

    def register(app: RouteRegistrationSinkV2) -> None:
        def connect() -> None:
            socket.create_connection(("127.0.0.1", 1))

        connect()
        app.add_api_route("/never", _endpoint, methods=["GET"], name="never")

    result = materialize_route_registration_v2(kind="helper", target=register)

    assert result.classification is RouteRegistrationClassificationV2.HYBRID
    assert result.ordered_signatures == ()
    assert called is False
    assert any("socket" in reason for reason in result.rejections)


@pytest.mark.unit
def test_registered_endpoint_resources_are_not_treated_as_factory_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden_connect(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)

    def resource_endpoint() -> dict[str, bool]:
        socket.create_connection(("127.0.0.1", 1))
        return {"ok": True}

    def factory() -> APIRouter:
        router = APIRouter()
        router.add_api_route(
            "/runtime-resource",
            resource_endpoint,
            methods=["GET"],
            name="runtime-resource",
        )
        return router

    result = materialize_route_registration_v2(kind="include_router", target=factory)

    assert result.classification is RouteRegistrationClassificationV2.ROUTES_ONLY
    assert result.ordered_signatures[0].path == "/runtime-resource"
    assert called is False


@pytest.mark.unit
def test_sink_violation_rolls_back_partially_registered_routes() -> None:
    def register(app: RouteRegistrationSinkV2) -> None:
        app.add_api_route("/partial", _endpoint, methods=["GET"], name="partial")
        app.state.forbidden = True

    result = materialize_route_registration_v2(kind="helper", target=register)

    assert result.classification is RouteRegistrationClassificationV2.HYBRID
    assert result.ordered_signatures == ()
    assert result.openapi_digest is None
    assert len(result.rejections) == 1
    assert "non-route effects forbidden" in result.rejections[0]
    assert "LOAD_ATTR:state" in result.rejections[0]


@pytest.mark.unit
def test_helper_failure_rolls_back_routes_and_restores_module_bindings() -> None:
    marker_name = "_TEMPORARY_ROUTE_REGISTRATION_BINDING"
    assert marker_name not in globals()

    def register(app: RouteRegistrationSinkV2) -> None:
        globals()[marker_name] = "temporary"
        app.add_api_route("/partial", _endpoint, methods=["GET"], name="partial")
        raise RuntimeError("registration failed")

    result = materialize_route_registration_v2(kind="helper", target=register)

    assert result.classification is RouteRegistrationClassificationV2.HYBRID
    assert result.ordered_signatures == ()
    assert result.rejections == ("route registration failed: RuntimeError",)
    assert marker_name not in globals()


@pytest.mark.unit
def test_async_non_route_helper_is_not_executed() -> None:
    called = False

    async def start_resource(_app: RouteRegistrationSinkV2) -> None:
        nonlocal called
        called = True

    result = materialize_route_registration_v2(kind="helper", target=start_resource)

    assert result.classification is RouteRegistrationClassificationV2.NON_ROUTE
    assert result.ordered_signatures == ()
    assert called is False
    assert result.rejections == ("async helpers are not executed during route catalog generation",)


@pytest.mark.unit
def test_materializer_rejects_unsupported_inventory_effect_kind() -> None:
    with pytest.raises(ValueError, match="unsupported route registration kind"):
        materialize_route_registration_v2(kind="middleware", target=lambda: None)
