"""Deterministic OpenAPI generation for immutable V2 route graphs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from fastapi import FastAPI, routing
from fastapi._compat import get_definitions
from fastapi._compat.v2 import (
    ModelField,
    TypeModelOrEnum,
    get_flat_models_from_fields,
    normalize_name,
)
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.models import OpenAPI
from fastapi.openapi.utils import get_fields_from_routes, get_openapi_path
from fastapi.types import ModelNameMap
from starlette.routing import BaseRoute

from .runtime import RuntimeV2Error


def build_openapi_schema_v2(app: FastAPI) -> dict[str, Any]:
    """Build one schema without hash-order-dependent component names."""
    info: dict[str, Any] = {"title": app.title, "version": app.version}
    if app.summary:
        info["summary"] = app.summary
    if app.description:
        info["description"] = app.description
    if app.terms_of_service:
        info["termsOfService"] = app.terms_of_service
    if app.contact:
        info["contact"] = app.contact
    if app.license_info:
        info["license"] = app.license_info

    output: dict[str, Any] = {"openapi": app.openapi_version, "info": info}
    if app.servers:
        output["servers"] = app.servers

    routes = tuple(app.routes)
    webhooks = tuple(app.webhooks.routes)
    components: dict[str, dict[str, Any]] = {}
    paths: dict[str, dict[str, Any]] = {}
    webhook_paths: dict[str, dict[str, Any]] = {}
    operation_ids: set[str] = set()
    all_fields = get_fields_from_routes([*routes, *webhooks])
    model_name_map = _stable_model_name_map(all_fields)
    field_mapping, definitions = get_definitions(
        fields=all_fields,
        model_name_map=model_name_map,
        separate_input_output_schemas=app.separate_input_output_schemas,
    )

    _collect_openapi_paths(
        routes,
        target=paths,
        components=components,
        definitions=definitions,
        operation_ids=operation_ids,
        model_name_map=model_name_map,
        field_mapping=field_mapping,
        separate_input_output_schemas=app.separate_input_output_schemas,
    )
    _collect_openapi_paths(
        webhooks,
        target=webhook_paths,
        components=components,
        definitions=definitions,
        operation_ids=operation_ids,
        model_name_map=model_name_map,
        field_mapping=field_mapping,
        separate_input_output_schemas=app.separate_input_output_schemas,
    )

    if definitions:
        components["schemas"] = {key: definitions[key] for key in sorted(definitions)}
    if components:
        output["components"] = components
    output["paths"] = paths
    if webhook_paths:
        output["webhooks"] = webhook_paths
    if app.openapi_tags:
        output["tags"] = app.openapi_tags
    if app.openapi_external_docs:
        output["externalDocs"] = app.openapi_external_docs

    return cast(
        dict[str, Any],
        jsonable_encoder(OpenAPI(**output), by_alias=True, exclude_none=True),
    )


def _stable_model_name_map(fields: list[ModelField]) -> ModelNameMap:
    models = get_flat_models_from_fields(fields, known_models=set())
    grouped: dict[str, list[TypeModelOrEnum]] = {}
    identities: dict[str, TypeModelOrEnum] = {}
    for model in models:
        identity = _model_identity(model)
        previous = identities.setdefault(identity, model)
        if previous is not model:
            raise RuntimeV2Error(
                "openapi_model_identity_conflict",
                f"multiple OpenAPI models share identity {identity}",
            )
        grouped.setdefault(normalize_name(model.__name__), []).append(model)

    result: ModelNameMap = {}
    owners: dict[str, TypeModelOrEnum] = {}
    for short_name in sorted(grouped):
        group = sorted(grouped[short_name], key=_model_identity)
        for model in group:
            component_name = short_name if len(group) == 1 else _qualified_model_name(model)
            previous = owners.setdefault(component_name, model)
            if previous is not model:
                raise RuntimeV2Error(
                    "openapi_model_name_conflict",
                    f"multiple OpenAPI models resolve to component {component_name}",
                )
            result[model] = component_name
    return result


def _model_identity(model: TypeModelOrEnum) -> str:
    return f"{model.__module__}.{model.__qualname__}"


def _qualified_model_name(model: TypeModelOrEnum) -> str:
    return normalize_name(f"{model.__module__}__{model.__qualname__}".replace(".", "__"))


def _collect_openapi_paths(
    routes: Sequence[BaseRoute],
    *,
    target: dict[str, dict[str, Any]],
    components: dict[str, dict[str, Any]],
    definitions: dict[str, dict[str, Any]],
    operation_ids: set[str],
    model_name_map: ModelNameMap,
    field_mapping: dict[Any, dict[str, Any]],
    separate_input_output_schemas: bool,
) -> None:
    for route in routes:
        if not isinstance(route, routing.APIRoute):
            continue
        result = get_openapi_path(
            route=route,
            operation_ids=operation_ids,
            model_name_map=model_name_map,
            field_mapping=field_mapping,
            separate_input_output_schemas=separate_input_output_schemas,
        )
        path, security_schemes, path_definitions = result
        if path:
            target.setdefault(route.path_format, {}).update(path)
        if security_schemes:
            components.setdefault("securitySchemes", {}).update(security_schemes)
        if path_definitions:
            definitions.update(path_definitions)


__all__ = ["build_openapi_schema_v2"]
