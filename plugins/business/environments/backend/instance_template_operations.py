"""Selected-tenant instance template reads, editing, and creation from the original wizard."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select

from plugins.business.environments.command_models import TemplateChange, TemplateRead
from src.application.schemas.instance_schemas import InstanceCreate
from src.application.schemas.instance_template_schemas import InstanceTemplateCreate
from src.infrastructure.adapters.primary.web.instance_deploy_application_authority_v2 import (
    instance_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.instance_template_application_authority_v2 import (
    instance_template_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import (
    instance_templates as templates,
    instances,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.persistence.models import ClusterModel, GeneMarketModel
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from src.host.operations.application_commands import Progress
    from src.host.operations.tenant_commands import TenantPackageContext

async def raw_read_templates(
    ctx: "TenantPackageContext", payload: dict[str, Any]
) -> dict[str, Any]:
    query = TemplateRead.model_validate(payload)
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant)
    async with asynccontextmanager(instance_template_application_authority_dependency_v2)(
        ctx.request, ctx.user, tenant, ctx.db
    ) as authority:
        if query.view == "list":
            page = await templates.list_templates(
                query.page, query.page_size, query.is_published, authority
            )
            return page.model_dump(mode="json")
        if not query.id:
            raise OptionalBusinessError("invalid_request", "A template ID is required")
        if query.view == "detail":
            return (await templates.get_template(query.id, authority)).model_dump(mode="json")
        items = await templates.list_template_items(query.id, authority)
        if query.view == "items":
            return {"items": [item.model_dump(mode="json") for item in items]}
        gene = GeneMarketModel
        rows = await ctx.db.execute(
            select(gene.id, gene.slug, gene.name)
            .where(
                gene.deleted_at.is_(None),
                or_(
                    gene.tenant_id == tenant, gene.tenant_id.is_(None) & gene.is_published.is_(True)
                ),
                gene.slug.in_([item.item_slug for item in items]),
            )
            .execution_options(populate_existing=True)
        )
        return {"items": [{"id": row.slug, "name": row.name} for row in rows]}


async def raw_change_template(
    ctx: "TenantPackageContext", payload: dict[str, Any]
) -> dict[str, Any]:
    edit = TemplateChange.model_validate(payload)
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant, require_admin=True)
    async with asynccontextmanager(instance_template_application_authority_dependency_v2)(
        ctx.request, ctx.user, tenant, ctx.db
    ) as authority:
        if edit.action == "create":
            row = await templates.create_template(
                InstanceTemplateCreate.model_validate(edit.data), authority
            )
        elif not edit.id:
            raise OptionalBusinessError("invalid_request", "A template ID is required")
        elif edit.action == "clone":
            row = await templates.clone_template(
                edit.id, templates.CloneTemplateRequest.model_validate(edit.data), authority
            )
        elif edit.action == "publish":
            row = await templates.publish_template(edit.id, authority)
        else:
            await templates.delete_template(edit.id, authority)
            return {"deleted": True}
        return {"row": row.model_dump(mode="json")}


async def read_templates(
    ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import read_templates as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def change_template(
    ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import change_template as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def raw_instance_access(ctx: "TenantPackageContext") -> dict[str, Any]:
    await require_tenant_access(ctx.db, ctx.user, ctx.scope.tenant_id)
    return {}


async def raw_cluster_owned(ctx: "TenantPackageContext", cluster_id: str) -> dict[str, Any]:
    found = await ctx.db.scalar(
        select(ClusterModel.id).where(
            ClusterModel.id == cluster_id, ClusterModel.tenant_id == ctx.scope.tenant_id
        )
    )
    return {"ok": found is not None}


async def raw_create_instance(
    ctx: "TenantPackageContext", payload: dict[str, Any]
) -> dict[str, Any]:
    data = InstanceCreate.model_validate(payload)
    async with asynccontextmanager(instance_application_authority_dependency_v2)(
        ctx.request, ctx.user, ctx.scope.tenant_id, ctx.db
    ) as authority:
        row = await instances.create_instance(data, authority)
    return {"id": row.id}


async def create_instance(
    ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import create_instance as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
