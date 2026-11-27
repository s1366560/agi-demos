"""Tenant-admin mutations used by the original cluster management form."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from plugins.business.environments.command_models import (
    ClusterCreateCommand as _Create,
    ClusterEditCommand as _Edit,
    ClusterUpdateCommand as _Update,
)
from src.application.schemas.cluster_schemas import ClusterCreate, ClusterUpdate
from src.infrastructure.adapters.primary.web.cluster_application_authority_v2 import (
    cluster_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import clusters
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access

if TYPE_CHECKING:
    from src.host.operations.application_commands import Progress
    from src.host.operations.tenant_commands import TenantPackageContext


async def raw_write_cluster(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
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
    return {"row": row.model_dump(mode="json")}


async def raw_delete_cluster(ctx: "TenantPackageContext", cluster_id: str) -> dict[str, Any]:
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant, require_admin=True)
    async with asynccontextmanager(cluster_application_authority_dependency_v2)(
        ctx.request, ctx.user, tenant, ctx.db
    ) as authority:
        await clusters.delete_cluster(cluster_id, authority)
    return {}


async def write_cluster(
    ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import write_cluster as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def delete_cluster(
    ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import delete_cluster as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
