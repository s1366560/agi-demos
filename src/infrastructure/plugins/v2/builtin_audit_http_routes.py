"""V2-owned production contributions for the builtin audit HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.application.schemas.audit_schemas import (
    AuditLogListResponse,
    RuntimeHookAuditSummaryResponse,
)
from src.infrastructure.adapters.primary.web.routers.audit import (
    export_audit_logs,
    get_runtime_hook_audit_summary,
    list_audit_logs,
    list_audit_logs_filtered,
    list_runtime_hook_audit_logs,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AUDIT_HTTP_ROUTES_ENTRY_V2 = "builtin-audit-http-routes"
AUDIT_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/audit-routes"
AUDIT_HTTP_ROUTES_ROW_V2 = "audit"
_AUDIT_PREFIX_V2 = "/api/v1/tenants/{tenant_id}/audit-logs"


def _audit_route_v2(
    *,
    path: str,
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=AUDIT_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=("GET",),
        endpoint=endpoint,
        name=name,
        tags=("audit-logs",),
        response_model=response_model,
        replaces_builtin_row_id=AUDIT_HTTP_ROUTES_ROW_V2,
    )


def audit_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``audit`` inventory row."""
    return (
        _audit_route_v2(
            path=_AUDIT_PREFIX_V2,
            endpoint=list_audit_logs,
            name="list_audit_logs",
            response_model=AuditLogListResponse,
        ),
        _audit_route_v2(
            path=f"{_AUDIT_PREFIX_V2}/filter",
            endpoint=list_audit_logs_filtered,
            name="list_audit_logs_filtered",
            response_model=AuditLogListResponse,
        ),
        _audit_route_v2(
            path=f"{_AUDIT_PREFIX_V2}/runtime-hooks",
            endpoint=list_runtime_hook_audit_logs,
            name="list_runtime_hook_audit_logs",
            response_model=AuditLogListResponse,
        ),
        _audit_route_v2(
            path=f"{_AUDIT_PREFIX_V2}/export",
            endpoint=export_audit_logs,
            name="export_audit_logs",
            response_model=None,
        ),
        _audit_route_v2(
            path=f"{_AUDIT_PREFIX_V2}/runtime-hooks/summary",
            endpoint=get_runtime_hook_audit_summary,
            name="get_runtime_hook_audit_summary",
            response_model=RuntimeHookAuditSummaryResponse,
        ),
    )


def builtin_audit_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the audit row as reversible route effects of one V2 Fiber."""
    definitions = audit_route_definitions_v2()

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

        await context.effect(setup, label=AUDIT_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=AUDIT_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AUDIT_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "AUDIT_HTTP_ROUTES_ENTRY_V2",
    "AUDIT_HTTP_ROUTES_MODULE_V2",
    "AUDIT_HTTP_ROUTES_ROW_V2",
    "audit_route_definitions_v2",
    "builtin_audit_http_routes_definition_v2",
]
