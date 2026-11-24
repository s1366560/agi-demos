"""Tenant-scoped runtime inventory for the signed Environments pages."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class InventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["instances", "clusters"]
    id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    page: int = Field(1, ge=1, le=1000000)


def _project(row: InstanceResponse | ClusterResponse, tenant: str) -> dict[str, Any]:
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
        fields.add("last_health_check")
    return row.model_dump(mode="json", include=fields, exclude_none=True)


async def inventory(
    ctx: "TenantPackageContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    query = InventoryQuery.model_validate(payload)
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant)
    if query.kind == "instances":
        async with asynccontextmanager(instance_application_authority_dependency_v2)(
            ctx.request, ctx.user, tenant, ctx.db
        ) as authority:
            if query.id:
                return {"item": _project(await instances.get_instance(query.id, authority), tenant)}
            result = await instances.list_instances(query.page, 20, authority)
            return {
                "items": [_project(row, tenant) for row in result.instances],
                "total": result.total,
            }
    async with asynccontextmanager(cluster_application_authority_dependency_v2)(
        ctx.request, ctx.user, tenant, ctx.db
    ) as cluster_authority:
        if query.id:
            return {
                "item": _project(await clusters.get_cluster(query.id, cluster_authority), tenant)
            }
        rows = await clusters.list_clusters(query.page, 20, cluster_authority)
        return {"items": [_project(row, tenant) for row in rows.clusters], "total": rows.total}
