"""V2-owned production contribution for the Cron HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.application.schemas.cron import (
    AutomationRunReceiptResponse,
    CronJobCapabilitiesResponse,
    CronJobListResponse,
    CronJobResponse,
    CronJobRunListResponse,
)
from src.infrastructure.adapters.primary.web.cron_application_authority_v2 import (
    cron_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.cron import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    get_cron_job_capabilities,
    list_cron_job_runs,
    list_cron_jobs,
    toggle_cron_job,
    trigger_manual_run,
    update_cron_job,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CRON_HTTP_ROUTES_ENTRY_V2 = "builtin-cron-http-routes"
CRON_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/cron-routes"
CRON_HTTP_ROUTES_ROW_V2 = "cron"


def cron_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``cron`` inventory row."""
    prefix = "/api/v1/projects/{project_id}/cron-jobs"
    return (
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=prefix,
            methods=("GET",),
            endpoint=list_cron_jobs,
            name="list_cron_jobs",
            tags=("cron-jobs",),
            response_model=CronJobListResponse,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/capabilities",
            methods=("GET",),
            endpoint=get_cron_job_capabilities,
            name="get_cron_job_capabilities",
            tags=("cron-jobs",),
            response_model=CronJobCapabilitiesResponse,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=prefix,
            methods=("POST",),
            endpoint=create_cron_job,
            name="create_cron_job",
            tags=("cron-jobs",),
            status_code=201,
            response_model=CronJobResponse,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/{{job_id}}",
            methods=("GET",),
            endpoint=get_cron_job,
            name="get_cron_job",
            tags=("cron-jobs",),
            response_model=CronJobResponse,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/{{job_id}}",
            methods=("PATCH",),
            endpoint=update_cron_job,
            name="update_cron_job",
            tags=("cron-jobs",),
            response_model=CronJobResponse,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/{{job_id}}",
            methods=("DELETE",),
            endpoint=delete_cron_job,
            name="delete_cron_job",
            tags=("cron-jobs",),
            status_code=204,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/{{job_id}}/toggle",
            methods=("POST",),
            endpoint=toggle_cron_job,
            name="toggle_cron_job",
            tags=("cron-jobs",),
            response_model=CronJobResponse,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/{{job_id}}/run",
            methods=("POST",),
            endpoint=trigger_manual_run,
            name="trigger_manual_run",
            tags=("cron-jobs",),
            status_code=202,
            response_model=CronJobResponse | AutomationRunReceiptResponse,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=CRON_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/{{job_id}}/runs",
            methods=("GET",),
            endpoint=list_cron_job_runs,
            name="list_cron_job_runs",
            tags=("cron-jobs",),
            response_model=CronJobRunListResponse,
            replaces_builtin_row_id=CRON_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_cron_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register Cron routes as one reversible V2 effect."""
    definitions = cron_route_definitions_v2()

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

        await context.effect(setup, label=CRON_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=CRON_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CRON_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "CRON_HTTP_ROUTES_ENTRY_V2",
    "CRON_HTTP_ROUTES_MODULE_V2",
    "CRON_HTTP_ROUTES_ROW_V2",
    "builtin_cron_http_routes_definition_v2",
    "cron_application_authority_dependency_v2",
    "cron_route_definitions_v2",
]
