"""Canonical FastAPI route metadata used by protocol V2 contract checks."""

from __future__ import annotations

import functools
import hashlib
import inspect
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

import rfc8785
from fastapi import FastAPI
from fastapi.datastructures import DefaultPlaceholder
from fastapi.params import Depends
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import BaseRoute, WebSocketRoute

from .openapi import build_openapi_schema_v2

_WEBSOCKET_METHOD_V2 = "WEBSOCKET"
_ROUTE_CONTRACT_APP_TITLE_V2 = "MemStack Route Contract V2"
_UNHANDLED_CONTRACT_VALUE_V2 = object()


class RouteRegistrationViolationV2(RuntimeError):
    """Raised when registration attempts to escape the route-only contract surface."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"forbidden route registration effect: {operation}")


@dataclass(frozen=True, kw_only=True)
class RouteSignatureV2:
    """One ordered HTTP/WebSocket signature plus its complete metadata digest."""

    path: str
    name: str
    methods: tuple[str, ...]
    metadata_digest: str

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "methods": list(self.methods),
            "metadata_digest": self.metadata_digest,
        }


def ordered_route_signatures_v2(routes: Sequence[BaseRoute]) -> tuple[RouteSignatureV2, ...]:
    """Return stable signatures while preserving registration order."""
    signatures: list[RouteSignatureV2] = []
    for route in routes:
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            raise RouteRegistrationViolationV2("unsupported route type")
        raw_methods = getattr(route, "methods", None)
        if raw_methods:
            methods = tuple(sorted(str(method).upper() for method in raw_methods))
        elif isinstance(route, WebSocketRoute):
            methods = (_WEBSOCKET_METHOD_V2,)
        else:
            raise RouteRegistrationViolationV2("unsupported route type")
        signatures.append(
            RouteSignatureV2(
                path=path,
                name=str(getattr(route, "name", "")),
                methods=methods,
                metadata_digest=_route_metadata_digest_v2(route),
            )
        )
    return tuple(signatures)


def create_route_contract_app_v2() -> FastAPI:
    """Create the deterministic private FastAPI graph used by every contract check."""
    return FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        title=_ROUTE_CONTRACT_APP_TITLE_V2,
    )


def route_openapi_digest_v2(app: FastAPI) -> str:
    """Digest one route graph's canonical OpenAPI document."""
    unique_ids = [
        (route, route.unique_id)
        for route in app.router.routes
        if isinstance(route, APIRoute) and route.operation_id is None
    ]
    try:
        for route, _unique_id in unique_ids:
            route.unique_id = _stable_generated_operation_id_v2(route)
        schema = build_openapi_schema_v2(app)
    finally:
        for route, unique_id in unique_ids:
            route.unique_id = unique_id
    canonical = rfc8785.dumps(cast("Any", schema))
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _stable_generated_operation_id_v2(route: APIRoute) -> str:
    stem = re.sub(r"\W", "_", f"{route.name}{route.path_format}")
    methods = "_".join(method.lower() for method in sorted(route.methods or ()))
    return f"{stem}_{methods}"


def _route_metadata_digest_v2(route: BaseRoute) -> str:
    payload = _route_metadata_payload_v2(route, seen=set())
    canonical = rfc8785.dumps(cast("Any", payload))
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _route_metadata_payload_v2(
    route: BaseRoute,
    *,
    seen: set[int],
) -> dict[str, object]:
    if id(route) in seen:
        return {"route_type": _symbol_identity_v2(type(route)), "recursive": True}
    seen.add(id(route))
    try:
        payload: dict[str, object] = {
            "route_type": _symbol_identity_v2(type(route)),
            "path": getattr(route, "path", None),
            "name": getattr(route, "name", None),
        }
        if isinstance(route, APIRoute):
            payload.update(_http_route_metadata_payload_v2(route, seen=seen))
        elif isinstance(route, APIWebSocketRoute):
            payload.update(
                {
                    "methods": [_WEBSOCKET_METHOD_V2],
                    "dependencies": _stable_contract_value_v2(route.dependencies),
                    "dependant": _dependant_contract_payload_v2(
                        route.dependant,
                        seen=set(),
                        include_call=False,
                    ),
                }
            )
        return payload
    finally:
        seen.remove(id(route))


def _http_route_metadata_payload_v2(
    route: APIRoute,
    *,
    seen: set[int],
) -> dict[str, object]:
    return {
        "methods": sorted(route.methods or ()),
        "path_format": route.path_format,
        "status_code": route.status_code,
        "tags": _stable_contract_value_v2(route.tags),
        "dependencies": _stable_contract_value_v2(route.dependencies),
        "summary": route.summary,
        "description": route.description,
        "response_description": route.response_description,
        "responses": _stable_contract_value_v2(route.responses),
        "deprecated": route.deprecated,
        "operation_id": route.operation_id,
        "response_model": _stable_contract_value_v2(route.response_model),
        "response_model_include": _stable_contract_value_v2(route.response_model_include),
        "response_model_exclude": _stable_contract_value_v2(route.response_model_exclude),
        "response_model_by_alias": route.response_model_by_alias,
        "response_model_exclude_unset": route.response_model_exclude_unset,
        "response_model_exclude_defaults": route.response_model_exclude_defaults,
        "response_model_exclude_none": route.response_model_exclude_none,
        "response_class": _stable_contract_value_v2(route.response_class),
        "callbacks": [
            _route_metadata_payload_v2(callback, seen=seen) for callback in route.callbacks or ()
        ],
        "openapi_extra": _stable_contract_value_v2(route.openapi_extra),
        "generate_unique_id_function": _stable_contract_value_v2(
            route.generate_unique_id_function
        ),
        "dependant": _dependant_contract_payload_v2(
            route.dependant,
            seen=set(),
            include_call=False,
        ),
        "include_in_schema": route.include_in_schema,
    }


def _dependant_contract_payload_v2(
    dependant: object,
    *,
    seen: set[int],
    include_call: bool = True,
) -> dict[str, object]:
    if id(dependant) in seen:
        recursive_payload: dict[str, object] = {"recursive": True}
        if include_call:
            recursive_payload["call"] = _stable_contract_value_v2(
                getattr(dependant, "call", None)
            )
        return recursive_payload
    seen.add(id(dependant))
    try:
        payload: dict[str, object] = {
            "name": getattr(dependant, "name", None),
            "path": getattr(dependant, "path", None),
            "use_cache": getattr(dependant, "use_cache", None),
            "scope": getattr(dependant, "scope", None),
            "security_scopes": _stable_contract_value_v2(
                getattr(dependant, "security_scopes", None)
            ),
            "own_oauth_scopes": _stable_contract_value_v2(
                getattr(dependant, "own_oauth_scopes", None)
            ),
            "dependencies": [
                _dependant_contract_payload_v2(child, seen=seen, include_call=True)
                for child in getattr(dependant, "dependencies", ())
            ],
        }
        if include_call:
            payload["call"] = _stable_contract_value_v2(getattr(dependant, "call", None))
        return payload
    finally:
        seen.remove(id(dependant))


def _stable_contract_value_v2(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    encoded = _stable_special_contract_value_v2(value)
    if encoded is not _UNHANDLED_CONTRACT_VALUE_V2:
        return encoded
    return _stable_collection_contract_value_v2(value)


def _stable_special_contract_value_v2(value: object) -> object:
    if isinstance(value, bytes):
        encoded: object = {"bytes": value.hex()}
    elif isinstance(value, Enum):
        encoded = {
            "enum": _symbol_identity_v2(type(value)),
            "value": _stable_contract_value_v2(value.value),
        }
    elif isinstance(value, DefaultPlaceholder):
        encoded = {"fastapi_default": _stable_contract_value_v2(value.value)}
    elif isinstance(value, Depends):
        encoded = {
            "depends": _stable_contract_value_v2(value.dependency),
            "use_cache": value.use_cache,
            "scope": getattr(value, "scope", None),
        }
    elif isinstance(value, BaseRoute):
        encoded = _route_metadata_payload_v2(value, seen=set())
    elif isinstance(value, functools.partial):
        encoded = {
            "partial": _stable_contract_value_v2(value.func),
            "args": [_stable_contract_value_v2(item) for item in value.args],
            "keywords": _stable_contract_value_v2(value.keywords or {}),
        }
    elif inspect.isclass(value) or inspect.isroutine(value):
        encoded = {"symbol": _symbol_identity_v2(value)}
    else:
        encoded = _UNHANDLED_CONTRACT_VALUE_V2
    return encoded


def _stable_collection_contract_value_v2(value: object) -> object:
    if isinstance(value, Mapping):
        pairs = [
            (_stable_contract_value_v2(key), _stable_contract_value_v2(child))
            for key, child in value.items()
        ]
        pairs.sort(key=lambda pair: rfc8785.dumps(cast("Any", pair[0])))
        encoded: object = {"mapping": [[key, child] for key, child in pairs]}
    elif isinstance(value, (set, frozenset)):
        items = [_stable_contract_value_v2(item) for item in value]
        items.sort(key=lambda item: rfc8785.dumps(cast("Any", item)))
        encoded = {"set": items}
    elif isinstance(value, Sequence):
        encoded = [_stable_contract_value_v2(item) for item in value]
    elif callable(value):
        encoded = {"callable": _symbol_identity_v2(type(value))}
    else:
        encoded = {"object_type": _symbol_identity_v2(type(value))}
    return encoded


def _symbol_identity_v2(value: object) -> str:
    module = getattr(value, "__module__", type(value).__module__)
    qualname = getattr(value, "__qualname__", type(value).__qualname__)
    return f"{module}:{qualname}"


__all__ = [
    "RouteRegistrationViolationV2",
    "RouteSignatureV2",
    "create_route_contract_app_v2",
    "ordered_route_signatures_v2",
    "route_openapi_digest_v2",
]
