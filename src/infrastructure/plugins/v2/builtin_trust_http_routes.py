"""V2-owned production contributions for the builtin trust HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.application.schemas.trust_schemas import (
    DecisionRecordListResponse,
    DecisionRecordResponse,
    TrustCheckResponse,
    TrustPolicyListResponse,
    TrustPolicyResponse,
)
from src.infrastructure.adapters.primary.web.routers.trust import (
    check_trust,
    create_trust_policy,
    get_decision_record,
    list_decision_records,
    list_trust_policies,
    resolve_approval_request,
    revoke_trust_policy,
    submit_approval_request,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TRUST_HTTP_ROUTES_ENTRY_V2 = "builtin-trust-http-routes"
TRUST_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/trust-routes"
TRUST_HTTP_ROUTES_ROW_V2 = "trust"
_TRUST_PREFIX_V2 = "/api/v1/tenants/{tenant_id}/trust"


def _trust_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=TRUST_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("trust",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=TRUST_HTTP_ROUTES_ROW_V2,
    )


def trust_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``trust`` inventory row."""
    return (
        _trust_route_v2(
            path=f"{_TRUST_PREFIX_V2}/policies",
            methods=("GET",),
            endpoint=list_trust_policies,
            name="list_trust_policies",
            response_model=TrustPolicyListResponse,
        ),
        _trust_route_v2(
            path=f"{_TRUST_PREFIX_V2}/policies",
            methods=("POST",),
            endpoint=create_trust_policy,
            name="create_trust_policy",
            response_model=TrustPolicyResponse,
            status_code=201,
        ),
        _trust_route_v2(
            path=f"{_TRUST_PREFIX_V2}/policies/{{policy_id}}",
            methods=("DELETE",),
            endpoint=revoke_trust_policy,
            name="revoke_trust_policy",
            response_model=TrustPolicyResponse,
        ),
        _trust_route_v2(
            path=f"{_TRUST_PREFIX_V2}/policies/check",
            methods=("GET",),
            endpoint=check_trust,
            name="check_trust",
            response_model=TrustCheckResponse,
        ),
        _trust_route_v2(
            path=f"{_TRUST_PREFIX_V2}/approval-requests",
            methods=("POST",),
            endpoint=submit_approval_request,
            name="submit_approval_request",
            response_model=DecisionRecordResponse,
            status_code=201,
        ),
        _trust_route_v2(
            path=f"{_TRUST_PREFIX_V2}/approval-requests/{{record_id}}/resolve",
            methods=("POST",),
            endpoint=resolve_approval_request,
            name="resolve_approval_request",
            response_model=DecisionRecordResponse,
        ),
        _trust_route_v2(
            path=f"{_TRUST_PREFIX_V2}/decision-records",
            methods=("GET",),
            endpoint=list_decision_records,
            name="list_decision_records",
            response_model=DecisionRecordListResponse,
        ),
        _trust_route_v2(
            path=f"{_TRUST_PREFIX_V2}/decision-records/{{record_id}}",
            methods=("GET",),
            endpoint=get_decision_record,
            name="get_decision_record",
            response_model=DecisionRecordResponse,
        ),
    )


def builtin_trust_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the trust row as reversible route effects of one V2 Fiber."""
    definitions = trust_route_definitions_v2()

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

        await context.effect(setup, label=TRUST_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=TRUST_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TRUST_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TRUST_HTTP_ROUTES_ENTRY_V2",
    "TRUST_HTTP_ROUTES_MODULE_V2",
    "TRUST_HTTP_ROUTES_ROW_V2",
    "builtin_trust_http_routes_definition_v2",
    "trust_route_definitions_v2",
]
