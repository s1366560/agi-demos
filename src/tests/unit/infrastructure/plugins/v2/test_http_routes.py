"""Immutable route table, OpenAPI, and generation dispatch tests."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI, Request, Response, WebSocket
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import create_model

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import (
    GenerationRouteDispatcherV2,
    RouteDefinitionV2,
    RouteTableRegistryV2,
    RouteTableV2,
    WebSocketRouteDefinitionV2,
    install_route_definitions_v2,
)
from src.infrastructure.plugins.v2.route_registration import (
    create_route_contract_app_v2,
    ordered_route_signatures_v2,
    route_openapi_digest_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]


def _table(value: str) -> RouteTableV2:
    async def endpoint() -> dict[str, str]:
        return {"generation": value}

    return RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="builtin-http",
                path="/api/value",
                methods=("GET",),
                endpoint=endpoint,
                name=f"value-{value}",
                tags=("Plugin V2",),
            ),
        )
    )


@pytest.mark.unit
def test_route_table_rejects_conflicts_without_mutating_outer_routes() -> None:
    route = _table("one").definitions[0]

    with pytest.raises(RuntimeV2Error) as error:
        RouteTableV2((route, route))

    assert error.value.code == "route_conflict"


@pytest.mark.unit
def test_route_table_supports_http_and_websocket_contributions_at_one_path() -> None:
    async def http_endpoint() -> dict[str, str]:
        return {"transport": "http"}

    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"transport": "websocket"})
        await websocket.close()

    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="mixed-transport",
                path="/api/mixed",
                methods=("GET",),
                endpoint=http_endpoint,
                name="mixed-http",
                response_model=dict[str, str],
            ),
            WebSocketRouteDefinitionV2(
                owner_entry_id="mixed-transport",
                path="/api/mixed",
                endpoint=websocket_endpoint,
                name="mixed-websocket",
            ),
        )
    )
    descriptor = PluginGenerationDescriptorV2(
        profile_id="mixed-transport",
        generation=1,
        digest="0" * 64,
    )
    app = FastAPI()
    app.mount("/", table)

    with TestClient(app) as client:
        assert client.get("/api/mixed").json() == {"transport": "http"}
        with client.websocket_connect("/api/mixed") as websocket:
            assert websocket.receive_json() == {"transport": "websocket"}

    assert "/api/mixed" in table.openapi_snapshot(descriptor).schema["paths"]


@pytest.mark.unit
def test_route_table_applies_declared_route_class_override() -> None:
    class HeaderRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            original_route_handler = super().get_route_handler()

            async def route_handler(request: Request) -> Response:
                response = await original_route_handler(request)
                response.headers["x-v2-route-class"] = "applied"
                return response

            return route_handler

    async def endpoint() -> dict[str, bool]:
        return {"ok": True}

    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="custom-route-class",
                path="/api/custom-route-class",
                methods=("GET",),
                endpoint=endpoint,
                name="custom-route-class",
                route_class_override=HeaderRoute,
            ),
        )
    )
    app = FastAPI()
    app.mount("/", table)

    with TestClient(app) as client:
        response = client.get("/api/custom-route-class")

    assert response.status_code == 200
    assert response.headers["x-v2-route-class"] == "applied"


@pytest.mark.unit
def test_route_table_preserves_explicit_openapi_metadata() -> None:
    async def endpoint() -> dict[str, bool]:
        """Inferred description that must not replace the explicit contract."""
        return {"ok": True}

    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="explicit-openapi-metadata",
                path="/api/explicit-openapi-metadata",
                methods=("GET",),
                endpoint=endpoint,
                name="explicit-openapi-metadata",
                summary="Explicit summary",
                description="Explicit description",
                deprecated=True,
            ),
        )
    )
    descriptor = PluginGenerationDescriptorV2(
        profile_id="explicit-openapi-metadata",
        generation=1,
        digest="0" * 64,
    )

    operation = table.openapi_snapshot(descriptor).schema["paths"][
        "/api/explicit-openapi-metadata"
    ]["get"]

    assert operation["summary"] == "Explicit summary"
    assert operation["description"] == "Explicit description"
    assert operation["deprecated"] is True


@pytest.mark.unit
def test_route_definition_round_trips_complete_fastapi_metadata() -> None:
    callback_router = FastAPI()

    @callback_router.post("/callback", name="callback")
    async def callback() -> dict[str, bool]:
        return {"accepted": True}

    callback_route = next(
        route for route in callback_router.router.routes if isinstance(route, APIRoute)
    )

    async def endpoint() -> dict[str, object]:
        return {"public": "value", "private": "hidden"}

    def unique_id(route: APIRoute) -> str:
        return f"v2_{route.name}"

    app = FastAPI()
    install_route_definitions_v2(
        app,
        (
            RouteDefinitionV2(
                owner_entry_id="complete-fastapi-metadata",
                path="/api/complete-fastapi-metadata",
                methods=("POST",),
                endpoint=endpoint,
                name="complete-fastapi-metadata",
                summary="Complete summary",
                description="Complete description",
                response_description="Complete response",
                responses={418: {"description": "Teapot"}},
                deprecated=True,
                operation_id="completeMetadataOperation",
                openapi_extra={"x-plugin-contract": "v2"},
                callbacks=(callback_route,),
                response_model=dict[str, object],
                response_model_include={"public"},
                response_model_exclude={"private"},
                response_model_by_alias=False,
                response_model_exclude_unset=True,
                response_model_exclude_defaults=True,
                response_model_exclude_none=True,
                generate_unique_id_function=unique_id,
            ),
        ),
    )

    route = next(route for route in app.router.routes if isinstance(route, APIRoute))
    operation = app.openapi()["paths"]["/api/complete-fastapi-metadata"]["post"]

    assert route.response_description == "Complete response"
    assert route.responses == {418: {"description": "Teapot"}}
    assert route.operation_id == "completeMetadataOperation"
    assert route.openapi_extra == {"x-plugin-contract": "v2"}
    assert route.callbacks == [callback_route]
    assert route.response_model_include == {"public"}
    assert route.response_model_exclude == {"private"}
    assert route.response_model_by_alias is False
    assert route.response_model_exclude_unset is True
    assert route.response_model_exclude_defaults is True
    assert route.response_model_exclude_none is True
    assert route.generate_unique_id_function is unique_id
    assert operation["operationId"] == "completeMetadataOperation"
    assert operation["x-plugin-contract"] == "v2"
    assert operation["responses"]["200"]["description"] == "Complete response"
    assert operation["responses"]["418"]["description"] == "Teapot"


@pytest.mark.unit
def test_route_metadata_digest_covers_complete_fastapi_contract() -> None:
    async def endpoint() -> dict[str, object]:
        return {"ok": True}

    async def dependency() -> str:
        return "ok"

    def unique_id(route: APIRoute) -> str:
        return f"contract_{route.name}"

    class CustomRoute(APIRoute):
        pass

    callback_app = FastAPI()

    @callback_app.post("/callback", name="callback")
    async def callback() -> dict[str, bool]:
        return {"ok": True}

    callback_route = next(
        route for route in callback_app.router.routes if isinstance(route, APIRoute)
    )
    baseline = RouteDefinitionV2(
        owner_entry_id="metadata-digest",
        path="/api/metadata-digest",
        methods=("POST",),
        endpoint=endpoint,
        name="metadata-digest",
        response_model=dict[str, object],
    )
    mutations: tuple[dict[str, object], ...] = (
        {"dependencies": (Depends(dependency),)},
        {"tags": ("changed",)},
        {"summary": "Changed summary"},
        {"description": "Changed description"},
        {"response_description": "Changed response"},
        {"responses": {418: {"description": "Teapot"}}},
        {"deprecated": True},
        {"operation_id": "changedOperation"},
        {"openapi_extra": {"x-contract": "changed"}},
        {"callbacks": (callback_route,)},
        {"status_code": 201},
        {"response_model": list[dict[str, object]]},
        {"response_model_include": {"ok"}},
        {"response_model_exclude": {"hidden"}},
        {"response_model_by_alias": False},
        {"response_model_exclude_unset": True},
        {"response_model_exclude_defaults": True},
        {"response_model_exclude_none": True},
        {"response_class": Response},
        {"route_class_override": CustomRoute},
        {"generate_unique_id_function": unique_id},
        {"include_in_schema": False},
    )

    baseline_metadata, baseline_openapi = _route_contract_digests(baseline)

    for mutation in mutations:
        candidate = replace(baseline, **mutation)
        candidate_metadata, candidate_openapi = _route_contract_digests(candidate)
        assert (candidate_metadata, candidate_openapi) != (
            baseline_metadata,
            baseline_openapi,
        ), mutation


@pytest.mark.unit
def test_default_response_model_sentinel_differs_from_explicit_none() -> None:
    async def endpoint() -> dict[str, bool]:
        return {"ok": True}

    inferred = RouteDefinitionV2(
        owner_entry_id="response-model-sentinel",
        path="/api/response-model-sentinel",
        methods=("GET",),
        endpoint=endpoint,
        name="response-model-sentinel",
    )
    disabled = replace(inferred, response_model=None)

    assert _route_contract_digests(inferred) != _route_contract_digests(disabled)


@pytest.mark.unit
def test_endpoint_wrapper_identity_is_not_part_of_the_public_route_contract() -> None:
    async def first() -> dict[str, bool]:
        return {"ok": True}

    async def second() -> dict[str, bool]:
        return {"ok": True}

    baseline = RouteDefinitionV2(
        owner_entry_id="endpoint-wrapper",
        path="/api/endpoint-wrapper",
        methods=("GET",),
        endpoint=first,
        name="endpoint-wrapper",
        summary="Endpoint wrapper",
        description="Stable public contract.",
        response_model=dict[str, bool],
    )

    assert _route_contract_digests(baseline) == _route_contract_digests(
        replace(baseline, endpoint=second)
    )


@pytest.mark.unit
def test_nested_dependency_identity_changes_route_metadata_digest() -> None:
    async def first_dependency() -> str:
        return "first"

    async def second_dependency() -> str:
        return "second"

    async def endpoint() -> dict[str, bool]:
        return {"ok": True}

    baseline = RouteDefinitionV2(
        owner_entry_id="nested-dependency",
        path="/api/nested-dependency",
        methods=("GET",),
        endpoint=endpoint,
        name="nested-dependency",
        dependencies=(Depends(first_dependency),),
        response_model=dict[str, bool],
    )
    changed = replace(
        baseline,
        dependencies=(Depends(second_dependency),),
    )

    assert _route_contract_digests(baseline) != _route_contract_digests(changed)


def _route_contract_digests(definition: RouteDefinitionV2) -> tuple[str, str]:
    app = create_route_contract_app_v2()
    install_route_definitions_v2(app, (definition,))
    signature = ordered_route_signatures_v2(app.router.routes)[0]
    return signature.metadata_digest, route_openapi_digest_v2(app)


@pytest.mark.unit
def test_route_table_preserves_fastapi_metadata_inference_by_default() -> None:
    async def inferred_metadata_endpoint() -> dict[str, bool]:
        """Inferred metadata description."""
        return {"ok": True}

    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="inferred-openapi-metadata",
                path="/api/inferred-openapi-metadata",
                methods=("GET",),
                endpoint=inferred_metadata_endpoint,
                name="inferred-openapi-metadata",
            ),
        )
    )
    descriptor = PluginGenerationDescriptorV2(
        profile_id="inferred-openapi-metadata",
        generation=1,
        digest="0" * 64,
    )

    operation = table.openapi_snapshot(descriptor).schema["paths"][
        "/api/inferred-openapi-metadata"
    ]["get"]

    assert operation["summary"] == "Inferred-Openapi-Metadata"
    assert operation["description"] == "Inferred metadata description."
    assert "deprecated" not in operation


@pytest.mark.unit
def test_route_table_rejects_duplicate_websocket_contributions() -> None:
    async def websocket_endpoint(_websocket: WebSocket) -> None:
        return None

    route = WebSocketRouteDefinitionV2(
        owner_entry_id="duplicate-websocket",
        path="/api/ws",
        endpoint=websocket_endpoint,
        name="duplicate-websocket",
    )

    with pytest.raises(RuntimeV2Error) as error:
        RouteTableV2((route, route))

    assert error.value.code == "route_conflict"


@pytest.mark.unit
def test_openapi_uses_stable_qualified_names_for_colliding_models() -> None:
    first_payload = create_model(
        "CollisionPayload",
        value=(str, ...),
        __module__="tests.openapi.first",
    )
    second_payload = create_model(
        "CollisionPayload",
        count=(int, ...),
        __module__="tests.openapi.second",
    )

    async def first_endpoint() -> object:
        return {"value": "first"}

    async def second_endpoint() -> object:
        return {"count": 2}

    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="first-http",
                path="/api/first",
                methods=("GET",),
                endpoint=first_endpoint,
                name="first",
                response_model=first_payload,
            ),
            RouteDefinitionV2(
                owner_entry_id="second-http",
                path="/api/second",
                methods=("GET",),
                endpoint=second_endpoint,
                name="second",
                response_model=second_payload,
            ),
        )
    )
    descriptor = PluginGenerationDescriptorV2(
        profile_id="openapi-collision",
        generation=1,
        digest="0" * 64,
    )

    components = table.openapi_snapshot(descriptor).schema["components"]["schemas"]
    assert "CollisionPayload" not in components
    assert {
        "tests__openapi__first__CollisionPayload",
        "tests__openapi__second__CollisionPayload",
    } <= components.keys()


@pytest.mark.unit
async def test_route_table_stages_without_visibility_until_atomic_activation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    distribution = host.current_distribution
    assert distribution is not None
    registry = RouteTableRegistryV2()

    staged = registry.stage(distribution.descriptor, _table("one"))

    assert registry.current is None
    assert registry.resolve(distribution.descriptor) is staged

    registry.activate(staged)
    assert registry.current is staged
    assert registry.current.openapi.descriptor == distribution.descriptor
    await host.close()


@pytest.mark.unit
async def test_dispatch_and_openapi_are_pinned_to_the_same_generation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    registry = RouteTableRegistryV2()
    first_distribution = host.current_distribution
    assert first_distribution is not None
    first_publication = await registry.publish(first_distribution.descriptor, _table("one"))
    dispatcher = GenerationRouteDispatcherV2(registry)

    async with pin_operation_context_v2(
        host,
        operation_id="old-http-request",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ):
        await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=2,
            version=2,
            nonce="route-generation-2",
        )
        second_distribution = host.current_distribution
        assert second_distribution is not None
        second_publication = await registry.publish(second_distribution.descriptor, _table("two"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=dispatcher),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/value")

        assert response.json() == {"generation": "one"}
        assert first_publication.openapi.descriptor.generation == 1
        assert "/api/value" in first_publication.openapi.schema["paths"]
        assert registry.current is second_publication

    async with (
        pin_operation_context_v2(
            host,
            operation_id="new-http-request",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=dispatcher),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/api/value")

    assert response.json() == {"generation": "two"}
    assert second_publication.openapi.descriptor.generation == 2
    await host.close()
