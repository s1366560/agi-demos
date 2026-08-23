"""V2-owned production contributions for the builtin subagents HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.subagents import (
    FilesystemSubAgentListResponse,
    SubAgentListResponse,
    SubAgentMatchResponse,
    SubAgentResponse,
    SubAgentStatsResponse,
    TemplateListResponse,
    TemplateResponse,
    create_subagent,
    create_template,
    delete_subagent,
    delete_template,
    export_subagent_as_template,
    get_subagent,
    get_subagent_stats,
    get_template,
    import_filesystem_subagent,
    install_template,
    list_filesystem_subagents,
    list_subagent_templates,
    list_subagents,
    list_template_categories,
    match_subagent,
    seed_templates,
    toggle_subagent_enabled,
    update_subagent,
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

SUBAGENTS_HTTP_ROUTES_ENTRY_V2 = "builtin-subagents-http-routes"
SUBAGENTS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/subagents-routes"
SUBAGENTS_HTTP_ROUTES_ROW_V2 = "subagents"
_SUBAGENTS_PREFIX_V2 = "/api/v1/subagents"


def _subagents_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=SUBAGENTS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("SubAgents",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=SUBAGENTS_HTTP_ROUTES_ROW_V2,
    )


def subagents_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``subagents`` inventory row."""
    prefix = _SUBAGENTS_PREFIX_V2
    mapping: tuple[
        tuple[str, tuple[str, ...], Callable[..., Any], str, object | None, int | None],
        ...,
    ] = (
        (f"{prefix}/", ("POST",), create_subagent, "create_subagent", SubAgentResponse, 201),
        (f"{prefix}/", ("GET",), list_subagents, "list_subagents", SubAgentListResponse, None),
        (
            f"{prefix}/filesystem",
            ("GET",),
            list_filesystem_subagents,
            "list_filesystem_subagents",
            FilesystemSubAgentListResponse,
            None,
        ),
        (
            f"{prefix}/filesystem/{{name}}/import",
            ("POST",),
            import_filesystem_subagent,
            "import_filesystem_subagent",
            SubAgentResponse,
            201,
        ),
        (
            f"{prefix}/templates/list",
            ("GET",),
            list_subagent_templates,
            "list_subagent_templates",
            TemplateListResponse,
            None,
        ),
        (
            f"{prefix}/templates/",
            ("POST",),
            create_template,
            "create_template",
            TemplateResponse,
            201,
        ),
        (
            f"{prefix}/templates/categories",
            ("GET",),
            list_template_categories,
            "list_template_categories",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/templates/{{template_id}}",
            ("GET",),
            get_template,
            "get_template",
            TemplateResponse,
            None,
        ),
        (
            f"{prefix}/templates/{{template_id}}",
            ("PUT",),
            update_template,
            "update_template",
            TemplateResponse,
            None,
        ),
        (
            f"{prefix}/templates/{{template_id}}",
            ("DELETE",),
            delete_template,
            "delete_template",
            None,
            204,
        ),
        (
            f"{prefix}/templates/{{template_id}}/install",
            ("POST",),
            install_template,
            "install_template",
            SubAgentResponse,
            201,
        ),
        (
            f"{prefix}/templates/from-subagent/{{subagent_id}}",
            ("POST",),
            export_subagent_as_template,
            "export_subagent_as_template",
            TemplateResponse,
            201,
        ),
        (
            f"{prefix}/{{subagent_id}}",
            ("GET",),
            get_subagent,
            "get_subagent",
            SubAgentResponse,
            None,
        ),
        (
            f"{prefix}/{{subagent_id}}",
            ("PUT",),
            update_subagent,
            "update_subagent",
            SubAgentResponse,
            None,
        ),
        (
            f"{prefix}/{{subagent_id}}",
            ("DELETE",),
            delete_subagent,
            "delete_subagent",
            None,
            204,
        ),
        (
            f"{prefix}/{{subagent_id}}/enable",
            ("PATCH",),
            toggle_subagent_enabled,
            "toggle_subagent_enabled",
            SubAgentResponse,
            None,
        ),
        (
            f"{prefix}/{{subagent_id}}/stats",
            ("GET",),
            get_subagent_stats,
            "get_subagent_stats",
            SubAgentStatsResponse,
            None,
        ),
        (
            f"{prefix}/match",
            ("POST",),
            match_subagent,
            "match_subagent",
            SubAgentMatchResponse,
            None,
        ),
        (
            f"{prefix}/templates/seed",
            ("POST",),
            seed_templates,
            "seed_templates",
            dict[str, Any],
            None,
        ),
    )
    return tuple(
        _subagents_route_v2(
            path=path,
            methods=methods,
            endpoint=endpoint,
            name=name,
            response_model=response_model,
            status_code=status_code,
        )
        for path, methods, endpoint, name, response_model, status_code in mapping
    )


def builtin_subagents_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register subagent routes as reversible effects of one V2 Fiber."""
    definitions = subagents_route_definitions_v2()

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

        await context.effect(setup, label=SUBAGENTS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=SUBAGENTS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SUBAGENTS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SUBAGENTS_HTTP_ROUTES_ENTRY_V2",
    "SUBAGENTS_HTTP_ROUTES_MODULE_V2",
    "SUBAGENTS_HTTP_ROUTES_ROW_V2",
    "builtin_subagents_http_routes_definition_v2",
    "subagents_route_definitions_v2",
]
