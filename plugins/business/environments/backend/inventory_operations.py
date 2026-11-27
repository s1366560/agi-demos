"""Tenant-scoped runtime inventory for the signed Environments pages."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from plugins.business.environments.command_models import InventoryQuery
from src.application.schemas.cluster_schemas import ClusterResponse
from src.application.schemas.instance_schemas import InstanceResponse
from src.infrastructure.adapters.primary.web.cluster_application_authority_v2 import (
    cluster_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.instance_deploy_application_authority_v2 import (
    instance_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import clusters, instances
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from src.host.operations.application_commands import Progress
    from src.host.operations.tenant_commands import TenantPackageContext


def project_inventory_row(row: InstanceResponse | ClusterResponse, tenant: str) -> dict[str, Any]:
    if row.tenant_id != tenant:
        raise OptionalBusinessError("forbidden", "Environment belongs to another tenant")
    fields = {
        "id",
        "name",
        "status",
        "health_status",
        "compute_provider",
        "created_at",
        "updated_at",
    }
    if isinstance(row, InstanceResponse):
        fields.update(
            {
                "description",
                "cluster_id",
                "runtime",
                "image_version",
                "replicas",
                "available_replicas",
                "cpu_request",
                "cpu_limit",
                "mem_request",
                "mem_limit",
                "current_revision",
            }
        )
    else:
        fields.update({"last_health_check", "proxy_endpoint"})
    return row.model_dump(mode="json", include=fields, exclude_none=True)


async def raw_inventory(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
    query = InventoryQuery.model_validate(payload)
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant)
    if query.kind == "instances":
        async with asynccontextmanager(instance_application_authority_dependency_v2)(
            ctx.request, ctx.user, tenant, ctx.db
        ) as authority:
            if query.id:
                row = await instances.get_instance(query.id, authority)
                return {"kind": "instance", "item": row.model_dump(mode="json")}
            result = await instances.list_instances(query.page, query.page_size, authority)
            return {
                "kind": "instance",
                "items": [row.model_dump(mode="json") for row in result.instances],
                "total": result.total,
            }
    async with asynccontextmanager(cluster_application_authority_dependency_v2)(
        ctx.request, ctx.user, tenant, ctx.db
    ) as cluster_authority:
        if query.health and query.id:
            health = await clusters.get_cluster_health(query.id, cluster_authority)
            return {"health": health.model_dump(mode="json")}
        if query.id:
            row = await clusters.get_cluster(query.id, cluster_authority)
            return {"kind": "cluster", "item": row.model_dump(mode="json")}
        rows = await clusters.list_clusters(query.page, query.page_size, cluster_authority)
        return {
            "kind": "cluster",
            "items": [row.model_dump(mode="json") for row in rows.clusters],
            "total": rows.total,
        }


async def inventory(
    ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import inventory as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
