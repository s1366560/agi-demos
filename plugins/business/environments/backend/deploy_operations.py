"""Run deployment reads and transitions in the tenant selected by the signed page."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.application.schemas.deploy_schemas import DeployCreate, DeployResponse
from src.infrastructure.adapters.primary.web.instance_deploy_application_authority_v2 import (
    deploy_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import deploy
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.host.operations.application_commands import Progress
    from src.host.operations.tenant_commands import TenantPackageContext
    from src.infrastructure.adapters.primary.web.instance_deploy_application_authority_v2 import (
        InstanceDeployApplicationAuthorityV2,
    )

type Identifier = Annotated[str, Field(min_length=1, max_length=128)]


class Read(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    view: Literal["list", "detail", "latest"]
    id: Identifier
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["create", "success", "failed", "cancel"]
    id: Identifier
    message: str = Field("", max_length=2000)


@asynccontextmanager
async def _authority(
    ctx: "TenantPackageContext", key: str, *, instance: bool
) -> "AsyncIterator[InstanceDeployApplicationAuthorityV2]":
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant)
    async with asynccontextmanager(deploy_application_authority_dependency_v2)(
        ctx.request, ctx.user, ctx.db
    ) as authority:
        access = authority.services.access
        lookup = access.find_instance_tenant_id if instance else access.find_deploy_tenant_id
        if await lookup(key) != tenant:
            raise OptionalBusinessError("page_not_found", "Deployment resource unavailable")
        yield authority


def _row(record: DeployResponse) -> dict[str, Any]:
    return {
        **record.model_dump(mode="json"),
        "completed_at": record.finished_at.isoformat() if record.finished_at else None,
        "description": record.message,
        "error_message": record.message if record.status == "failed" else None,
    }


async def read_deploys(
    ctx: "TenantPackageContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    query = Read.model_validate(payload)
    async with _authority(ctx, query.id, instance=query.view != "detail") as authority:
        if query.view == "list":
            page = await deploy.list_deploys(query.id, query.page, query.page_size, authority)
            return {
                **page.model_dump(exclude={"deploys"}),
                "deployments": [_row(row) for row in page.deploys],
            }
        getter = deploy.get_latest_deploy if query.view == "latest" else deploy.get_deploy
        return _row(await getter(query.id, authority))


async def change_deploy(
    ctx: "TenantPackageContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    item = Change.model_validate(payload)
    async with _authority(ctx, item.id, instance=item.action == "create") as authority:
        match item.action:
            case "create":
                row = await deploy.create_deploy(DeployCreate(instance_id=item.id), authority)
            case "success":
                row = await deploy.mark_deploy_success(
                    item.id, deploy.DeploySuccessRequest(message=item.message), authority
                )
            case "failed":
                row = await deploy.mark_deploy_failed(
                    item.id, deploy.DeployFailedRequest(message=item.message), authority
                )
            case "cancel":
                row = await deploy.cancel_deploy(item.id, authority)
        return _row(row)
