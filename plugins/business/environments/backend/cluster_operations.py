"""Tenant-admin mutations used by the original cluster management form."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.application.schemas.cluster_schemas import ClusterCreate, ClusterUpdate
from src.infrastructure.adapters.primary.web.cluster_application_authority_v2 import (
    cluster_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import clusters
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access

from .inventory_operations import project_inventory_row

if TYPE_CHECKING:
    from src.host.operations.application_commands import Progress
    from src.host.operations.tenant_commands import TenantPackageContext


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Key(_Input):
    id: str = Field(min_length=1, max_length=128)


class _Settings(_Input):
    name: str = Field(min_length=1, max_length=255)
    compute_provider: str | None = Field(None, max_length=50)
    proxy_endpoint: str | None = Field(None, max_length=2048)
    provider_config: dict[str, Any] | None = None


class _Create(_Input):
    action: Literal["create"]
    data: _Settings


class _Edit(_Key):
    action: Literal["edit"]


class _Update(_Key):
    action: Literal["update"]
    data: _Settings


async def write_cluster(
    ctx: "TenantPackageContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    from pydantic import TypeAdapter

    change: _Create | _Edit | _Update = TypeAdapter(
        Annotated[_Create | _Edit | _Update, Field(discriminator="action")]
    ).validate_python(payload)
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant, require_admin=True)
    async with asynccontextmanager(cluster_application_authority_dependency_v2)(
        ctx.request, ctx.user, tenant, ctx.db
    ) as authority:
        if isinstance(change, _Create):
            row = await clusters.create_cluster(
                ClusterCreate.model_validate(change.data.model_dump(exclude_none=True)), authority
            )
        elif isinstance(change, _Update):
            row = await clusters.update_cluster(
                change.id,
                ClusterUpdate.model_validate(change.data.model_dump(exclude_none=True)),
                authority,
            )
        else:
            row = await clusters.get_cluster(change.id, authority)
        result = project_inventory_row(row, tenant)
        result["provider_config"] = row.provider_config
        return {"item": result}


async def delete_cluster(
    ctx: "TenantPackageContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    key = _Key.model_validate(payload)
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant, require_admin=True)
    async with asynccontextmanager(cluster_application_authority_dependency_v2)(
        ctx.request, ctx.user, tenant, ctx.db
    ) as authority:
        await clusters.delete_cluster(key.id, authority)
    return {}
