"""V2-owned production contributions for the builtin instance-templates HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.instance_template_schemas import (
    InstanceTemplateListResponse,
    InstanceTemplateResponse,
    TemplateItemResponse,
)
from src.infrastructure.adapters.primary.web.routers.instance_templates import (
    add_template_item,
    clone_template,
    create_template,
    delete_template,
    get_template,
    list_template_items,
    list_templates,
    publish_template,
    remove_template_item,
    unpublish_template,
    update_template,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INSTANCE_TEMPLATES_HTTP_ROUTES_ENTRY_V2 = "builtin-instance-templates-http-routes"
INSTANCE_TEMPLATES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/instance-templates-routes"
INSTANCE_TEMPLATES_HTTP_ROUTES_ROW_V2 = "instance-templates"
_INSTANCE_TEMPLATES_PREFIX_V2 = "/api/v1/instance-templates"


def _instance_template_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=INSTANCE_TEMPLATES_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Instance Templates",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=INSTANCE_TEMPLATES_HTTP_ROUTES_ROW_V2,
    )


def instance_template_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``instance-templates`` inventory row."""
    prefix = _INSTANCE_TEMPLATES_PREFIX_V2
    return (
        _instance_template_route_v2(
            path=f"{prefix}/",
            methods=("POST",),
            endpoint=create_template,
            name="create_template",
            response_model=InstanceTemplateResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/",
            methods=("GET",),
            endpoint=list_templates,
            name="list_templates",
            response_model=InstanceTemplateListResponse,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}",
            methods=("GET",),
            endpoint=get_template,
            name="get_template",
            response_model=InstanceTemplateResponse,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}",
            methods=("PUT",),
            endpoint=update_template,
            name="update_template",
            response_model=InstanceTemplateResponse,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}",
            methods=("DELETE",),
            endpoint=delete_template,
            name="delete_template",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}/publish",
            methods=("POST",),
            endpoint=publish_template,
            name="publish_template",
            response_model=InstanceTemplateResponse,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}/unpublish",
            methods=("POST",),
            endpoint=unpublish_template,
            name="unpublish_template",
            response_model=InstanceTemplateResponse,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}/clone",
            methods=("POST",),
            endpoint=clone_template,
            name="clone_template",
            response_model=InstanceTemplateResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}/items",
            methods=("POST",),
            endpoint=add_template_item,
            name="add_template_item",
            response_model=TemplateItemResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}/items/{{item_id}}",
            methods=("DELETE",),
            endpoint=remove_template_item,
            name="remove_template_item",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _instance_template_route_v2(
            path=f"{prefix}/{{template_id}}/items",
            methods=("GET",),
            endpoint=list_template_items,
            name="list_template_items",
            response_model=list[TemplateItemResponse],
        ),
    )


def builtin_instance_templates_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register instance-template routes as reversible effects of one V2 Fiber."""
    definitions = instance_template_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label=INSTANCE_TEMPLATES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=INSTANCE_TEMPLATES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(INSTANCE_TEMPLATES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "INSTANCE_TEMPLATES_HTTP_ROUTES_ENTRY_V2",
    "INSTANCE_TEMPLATES_HTTP_ROUTES_MODULE_V2",
    "INSTANCE_TEMPLATES_HTTP_ROUTES_ROW_V2",
    "builtin_instance_templates_http_routes_definition_v2",
    "instance_template_route_definitions_v2",
]
