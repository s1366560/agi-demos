"""Tenant-scoped runner-pool operations for the signed cluster detail page."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from src.application.schemas.acp_runner_schemas import ACPRunnerPoolCreate, ACPRunnerTokenRequest
from src.infrastructure.adapters.primary.web.cluster_application_authority_v2 import (
    cluster_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import clusters
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.host.operations.application_commands import Progress
    from src.host.operations.tenant_commands import TenantPackageContext
    from src.infrastructure.adapters.primary.web.cluster_application_authority_v2 import (
        ClusterApplicationAuthorityV2,
    )


class _Cluster(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, Field(min_length=1, max_length=128)]


class _CreatePool(_Cluster):
    data: ACPRunnerPoolCreate


class _IssueToken(_Cluster):
    pool_key: Annotated[str, Field(min_length=1, max_length=120)]
    data: ACPRunnerTokenRequest


@asynccontextmanager
async def _authority(
    ctx: "TenantPackageContext", *, admin: bool
) -> "AsyncIterator[ClusterApplicationAuthorityV2]":
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant, require_admin=admin)
    async with asynccontextmanager(cluster_application_authority_dependency_v2)(
        ctx.request, ctx.user, tenant, ctx.db
    ) as authority:
        yield authority


async def list_pools(
    ctx: "TenantPackageContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    key = _Cluster.model_validate(payload)
    async with _authority(ctx, admin=False) as authority:
        pools = await clusters.list_cluster_acp_runner_pools(key.id, authority)
    return {"items": [pool.model_dump(mode="json", by_alias=True) for pool in pools]}


async def create_pool(
    ctx: "TenantPackageContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    change = _CreatePool.model_validate(payload)
    async with _authority(ctx, admin=True) as authority:
        pool = await clusters.create_cluster_acp_runner_pool(change.id, change.data, authority)
    return {"item": pool.model_dump(mode="json", by_alias=True)}


async def issue_token(
    ctx: "TenantPackageContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    change = _IssueToken.model_validate(payload)
    async with _authority(ctx, admin=True) as authority:
        result = await clusters.create_cluster_acp_runner_registration_token(
            change.id, change.pool_key, change.data, authority
        )
    return result.model_dump(mode="json", by_alias=True)
