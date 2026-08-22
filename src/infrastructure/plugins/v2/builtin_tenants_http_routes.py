"""V2-owned production contributions for the tenants HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.tenant import (
    TenantCreate,
    TenantListResponse,
    TenantResponse,
    TenantUpdate,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.project_tenant_authority_v2 import (
    ProjectTenantAuthorityV2,
    project_tenant_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.tenants import (
    TENANT_ANALYTICS_PROJECT_STORAGE_LIMIT,
    AddMemberRequest,
    GenePolicyRequest,
    GenePolicyResponse,
    RegistryRequest,
    RegistryResponse,
    TestConnectionResponse,
    UpdateMemberRoleRequest,
    add_tenant_member as _add_tenant_member,
    add_tenant_member_json as _add_tenant_member_json,
    create_registry as _create_registry,
    create_tenant as _create_tenant,
    delete_gene_policy as _delete_gene_policy,
    delete_registry as _delete_registry,
    delete_tenant as _delete_tenant,
    get_tenant as _get_tenant,
    get_tenant_analytics as _get_tenant_analytics,
    get_tenant_stats as _get_tenant_stats,
    list_gene_policies as _list_gene_policies,
    list_registries as _list_registries,
    list_tenant_members as _list_tenant_members,
    list_tenants as _list_tenants,
    remove_tenant_member as _remove_tenant_member,
    test_registry_connection as _test_registry_connection,
    update_registry as _update_registry,
    update_tenant as _update_tenant,
    update_tenant_member_role as _update_tenant_member_role,
    upsert_gene_policy as _upsert_gene_policy,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TENANTS_HTTP_ROUTES_ENTRY_V2 = "builtin-tenants-http-routes"
TENANTS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/tenants-routes"
TENANTS_HTTP_ROUTES_ROW_V2 = "tenants"


async def create_tenant_v2(
    tenant_data: TenantCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Create a new tenant."""
    return await _create_tenant(tenant_data, current_user, db)


async def list_tenants_v2(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str | None = Query(None, description="Search query"),
    current_user: User = Depends(get_current_user),
    project_tenant: ProjectTenantAuthorityV2 = Depends(project_tenant_authority_dependency_v2),
) -> TenantListResponse:
    """List tenants for the current user."""
    return await _list_tenants(page, page_size, search, current_user, project_tenant)


async def get_tenant_v2(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Get tenant by ID or slug."""
    return await _get_tenant(tenant_id, current_user, db)


async def update_tenant_v2(
    tenant_id: str,
    tenant_data: TenantUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Update tenant."""
    return await _update_tenant(tenant_id, tenant_data, current_user, db)


async def delete_tenant_v2(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete tenant."""
    await _delete_tenant(tenant_id, current_user, db)


async def add_tenant_member_v2(
    tenant_id: str,
    user_id: str,
    role: str = Query("member", description="Member role"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add member to tenant."""
    return await _add_tenant_member(tenant_id, user_id, role, current_user, db)


async def add_tenant_member_json_v2(
    tenant_id: str,
    body: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add member to tenant (JSON body version to match frontend)."""
    return await _add_tenant_member_json(tenant_id, body, current_user, db)


async def update_tenant_member_role_v2(
    tenant_id: str,
    user_id: str,
    body: UpdateMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update an existing tenant member role."""
    return await _update_tenant_member_role(tenant_id, user_id, body, current_user, db)


async def remove_tenant_member_v2(
    tenant_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove member from tenant."""
    await _remove_tenant_member(tenant_id, user_id, current_user, db)


async def list_tenant_members_v2(
    tenant_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List tenant members."""
    return await _list_tenant_members(tenant_id, request, current_user, db)


async def get_tenant_stats_v2(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get tenant statistics for the overview dashboard."""
    return await _get_tenant_stats(tenant_id, current_user, db)


async def get_tenant_analytics_v2(
    tenant_id: str,
    period: str = Query("30d", description="Time period: 7d, 30d, 90d"),
    project_storage_limit: int = Query(
        TENANT_ANALYTICS_PROJECT_STORAGE_LIMIT,
        ge=1,
        le=50,
        description="Maximum number of projects returned for the storage distribution chart",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get analytics data for tenant dashboard charts.

    Returns:
        - memoryGrowth: Time-series data for memory creation
        - projectStorage: Per-project storage distribution
        - summary: Quick stats
    """
    return await _get_tenant_analytics(
        tenant_id,
        period,
        project_storage_limit,
        current_user,
        db,
    )


async def list_gene_policies_v2(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GenePolicyResponse]:
    return await _list_gene_policies(tenant_id, current_user, db)


async def upsert_gene_policy_v2(
    tenant_id: str,
    policy_key: str,
    body: GenePolicyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenePolicyResponse:
    return await _upsert_gene_policy(tenant_id, policy_key, body, current_user, db)


async def delete_gene_policy_v2(
    tenant_id: str,
    policy_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _delete_gene_policy(tenant_id, policy_key, current_user, db)


async def list_registries_v2(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RegistryResponse]:
    return await _list_registries(tenant_id, current_user, db)


async def create_registry_v2(
    tenant_id: str,
    body: RegistryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RegistryResponse:
    return await _create_registry(tenant_id, body, current_user, db)


async def update_registry_v2(
    tenant_id: str,
    registry_id: str,
    body: RegistryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RegistryResponse:
    return await _update_registry(tenant_id, registry_id, body, current_user, db)


async def delete_registry_v2(
    tenant_id: str,
    registry_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _delete_registry(tenant_id, registry_id, current_user, db)


async def test_registry_connection_v2(
    tenant_id: str,
    registry_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResponse:
    return await _test_registry_connection(tenant_id, registry_id, current_user, db)


def _tenants_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    status_code: int | None = None,
    response_model: object | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=TENANTS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("tenants",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=TENANTS_HTTP_ROUTES_ROW_V2,
    )


def tenants_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``tenants`` inventory row."""
    tenant_path = "/api/v1/tenants/{tenant_id}"
    return (
        _tenants_route_v2(
            path="/api/v1/tenants/",
            methods=("POST",),
            endpoint=create_tenant_v2,
            name="create_tenant",
            status_code=status.HTTP_201_CREATED,
            response_model=TenantResponse,
        ),
        _tenants_route_v2(
            path="/api/v1/tenants/",
            methods=("GET",),
            endpoint=list_tenants_v2,
            name="list_tenants",
            response_model=TenantListResponse,
        ),
        _tenants_route_v2(
            path=tenant_path,
            methods=("GET",),
            endpoint=get_tenant_v2,
            name="get_tenant",
            response_model=TenantResponse,
        ),
        _tenants_route_v2(
            path=tenant_path,
            methods=("PUT",),
            endpoint=update_tenant_v2,
            name="update_tenant",
            response_model=TenantResponse,
        ),
        _tenants_route_v2(
            path=tenant_path,
            methods=("DELETE",),
            endpoint=delete_tenant_v2,
            name="delete_tenant",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members/{{user_id}}",
            methods=("POST",),
            endpoint=add_tenant_member_v2,
            name="add_tenant_member",
            status_code=status.HTTP_201_CREATED,
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members",
            methods=("POST",),
            endpoint=add_tenant_member_json_v2,
            name="add_tenant_member_json",
            status_code=status.HTTP_201_CREATED,
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members/{{user_id}}",
            methods=("PATCH",),
            endpoint=update_tenant_member_role_v2,
            name="update_tenant_member_role",
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members/{{user_id}}",
            methods=("DELETE",),
            endpoint=remove_tenant_member_v2,
            name="remove_tenant_member",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members",
            methods=("GET",),
            endpoint=list_tenant_members_v2,
            name="list_tenant_members",
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/stats",
            methods=("GET",),
            endpoint=get_tenant_stats_v2,
            name="get_tenant_stats",
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/analytics",
            methods=("GET",),
            endpoint=get_tenant_analytics_v2,
            name="get_tenant_analytics",
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/gene-policies",
            methods=("GET",),
            endpoint=list_gene_policies_v2,
            name="list_gene_policies",
            response_model=list[GenePolicyResponse],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/gene-policies/{{policy_key}}",
            methods=("PUT",),
            endpoint=upsert_gene_policy_v2,
            name="upsert_gene_policy",
            response_model=GenePolicyResponse,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/gene-policies/{{policy_key}}",
            methods=("DELETE",),
            endpoint=delete_gene_policy_v2,
            name="delete_gene_policy",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries",
            methods=("GET",),
            endpoint=list_registries_v2,
            name="list_registries",
            response_model=list[RegistryResponse],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries",
            methods=("POST",),
            endpoint=create_registry_v2,
            name="create_registry",
            status_code=status.HTTP_201_CREATED,
            response_model=RegistryResponse,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries/{{registry_id}}",
            methods=("PUT",),
            endpoint=update_registry_v2,
            name="update_registry",
            response_model=RegistryResponse,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries/{{registry_id}}",
            methods=("DELETE",),
            endpoint=delete_registry_v2,
            name="delete_registry",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries/{{registry_id}}/test",
            methods=("POST",),
            endpoint=test_registry_connection_v2,
            name="test_registry_connection",
            response_model=TestConnectionResponse,
        ),
    )


def builtin_tenants_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register tenants routes as reversible effects of one V2 Fiber."""
    definitions = tenants_route_definitions_v2()

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

        await context.effect(setup, label="builtin-tenants-http-routes")

    return PluginDefinitionV2(
        module_ref=TENANTS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TENANTS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TENANTS_HTTP_ROUTES_ENTRY_V2",
    "TENANTS_HTTP_ROUTES_MODULE_V2",
    "TENANTS_HTTP_ROUTES_ROW_V2",
    "AddMemberRequest",
    "GenePolicyRequest",
    "GenePolicyResponse",
    "RegistryRequest",
    "RegistryResponse",
    "TestConnectionResponse",
    "UpdateMemberRoleRequest",
    "add_tenant_member_json_v2",
    "add_tenant_member_v2",
    "builtin_tenants_http_routes_definition_v2",
    "create_registry_v2",
    "create_tenant_v2",
    "delete_gene_policy_v2",
    "delete_registry_v2",
    "delete_tenant_v2",
    "get_tenant_analytics_v2",
    "get_tenant_stats_v2",
    "get_tenant_v2",
    "list_gene_policies_v2",
    "list_registries_v2",
    "list_tenant_members_v2",
    "list_tenants_v2",
    "remove_tenant_member_v2",
    "tenants_route_definitions_v2",
    "test_registry_connection_v2",
    "update_registry_v2",
    "update_tenant_member_role_v2",
    "update_tenant_v2",
    "upsert_gene_policy_v2",
]
