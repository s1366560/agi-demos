"""V2-owned production contributions for workspace tool-grant HTTP routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.trust_schemas import (
    TrustPolicyListResponse,
    TrustPolicyResponse,
)
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.trust import (
    list_workspace_tool_grants as _list_workspace_tool_grants,
    revoke_workspace_tool_grant as _revoke_workspace_tool_grant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TRUST_WORKSPACE_HTTP_ROUTES_ENTRY_V2 = "builtin-trust-workspace-http-routes"
TRUST_WORKSPACE_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/trust-workspace-routes"
TRUST_WORKSPACE_HTTP_ROUTES_ROW_V2 = "trust-workspace"
_TOOL_GRANTS_PATH_V2 = (
    "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/tool-grants"
)


async def list_workspace_tool_grants_v2(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrustPolicyListResponse:
    return await _list_workspace_tool_grants(
        tenant_id,
        project_id,
        workspace_id,
        request,
        current_user,
        db,
    )


async def revoke_workspace_tool_grant_v2(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    policy_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrustPolicyResponse:
    return await _revoke_workspace_tool_grant(
        tenant_id,
        project_id,
        workspace_id,
        policy_id,
        request,
        current_user,
        db,
    )


def trust_workspace_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``trust-workspace`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=TRUST_WORKSPACE_HTTP_ROUTES_ENTRY_V2,
            path=_TOOL_GRANTS_PATH_V2,
            methods=("GET",),
            endpoint=list_workspace_tool_grants_v2,
            name="list_workspace_tool_grants",
            tags=("trust",),
            response_model=TrustPolicyListResponse,
            replaces_builtin_row_id=TRUST_WORKSPACE_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=TRUST_WORKSPACE_HTTP_ROUTES_ENTRY_V2,
            path=f"{_TOOL_GRANTS_PATH_V2}/{{policy_id}}",
            methods=("DELETE",),
            endpoint=revoke_workspace_tool_grant_v2,
            name="revoke_workspace_tool_grant",
            tags=("trust",),
            response_model=TrustPolicyResponse,
            replaces_builtin_row_id=TRUST_WORKSPACE_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_trust_workspace_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register workspace tool-grant routes as reversible effects of one V2 Fiber."""
    definitions = trust_workspace_route_definitions_v2()

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

        await context.effect(setup, label="builtin-trust-workspace-http-routes")

    return PluginDefinitionV2(
        module_ref=TRUST_WORKSPACE_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TRUST_WORKSPACE_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TRUST_WORKSPACE_HTTP_ROUTES_ENTRY_V2",
    "TRUST_WORKSPACE_HTTP_ROUTES_MODULE_V2",
    "TRUST_WORKSPACE_HTTP_ROUTES_ROW_V2",
    "builtin_trust_workspace_http_routes_definition_v2",
    "list_workspace_tool_grants_v2",
    "revoke_workspace_tool_grant_v2",
    "trust_workspace_route_definitions_v2",
]
