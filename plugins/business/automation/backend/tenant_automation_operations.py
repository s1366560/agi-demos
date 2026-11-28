"""Signed tenant commands for the event log and webhook management pages."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.adapters.primary.web.event_log_application_authority_v2 import (
    event_log_scope,
)
from src.infrastructure.adapters.primary.web.routers import events, tenant_webhooks
from src.infrastructure.adapters.primary.web.routers.agent.access import (
    get_tenant_role,
    require_tenant_access,
)
from src.infrastructure.adapters.primary.web.tenant_webhook_application_authority_v2 import (
    tenant_webhook_application_authority_context_v2,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from src.host.operations.application_commands import Progress
    from src.host.operations.tenant_commands import TenantPackageContext


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Events(_Input):
    event_type: str | None = Field(None, max_length=256)
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class _Create(_Input):
    data: tenant_webhooks.WebhookCreateRequest


class _Key(_Input):
    id: str = Field(min_length=1, max_length=128)


class _Update(_Key):
    data: tenant_webhooks.WebhookUpdateRequest


async def raw_read_events(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
    query = _Events.model_validate(payload)
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant)
    async with event_log_scope(ctx.request, ctx.user, ctx.db, tenant) as authority:
        result = await events.list_events(
            **query.model_dump(), tenant_id=tenant, service=authority.services
        )
        return result.model_dump(mode="json")


async def raw_event_types(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
    _Input.model_validate(payload)
    tenant = ctx.scope.tenant_id
    role = await get_tenant_role(ctx.db, ctx.user, tenant)
    if role is None:
        raise OptionalBusinessError("forbidden", "Tenant membership required")
    async with event_log_scope(ctx.request, ctx.user, ctx.db, tenant) as authority:
        return {"role": role, "items": await events.list_event_types(tenant, authority.services)}


async def raw_list_hooks(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
    _Input.model_validate(payload)
    rows = await tenant_webhooks.list_webhooks(ctx.scope.tenant_id, ctx.request, ctx.user, ctx.db)
    return {"items": [row.model_dump(mode="json") for row in rows]}


async def raw_create_hook(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
    change = _Create.model_validate(payload)
    row = await tenant_webhooks.create_webhook(
        ctx.scope.tenant_id, change.data, ctx.request, ctx.user, ctx.db
    )
    return row.model_dump(mode="json")


async def _change_hook(ctx: "TenantPackageContext", change: _Key | _Update) -> dict[str, Any]:
    tenant = ctx.scope.tenant_id
    await require_tenant_access(ctx.db, ctx.user, tenant, require_admin=True)
    async with tenant_webhook_application_authority_context_v2(
        request=ctx.request, current_user=ctx.user, db=ctx.db, tenant_id=tenant
    ) as authority:
        service = authority.services.webhooks
        row = await service.get_webhook(change.id)
        if row is None or row.tenant_id != tenant:
            raise OptionalBusinessError("not_found", "Webhook unavailable")
        if isinstance(change, _Update):
            row = await service.update_webhook(webhook_id=change.id, **change.data.model_dump())
            result = tenant_webhooks._to_webhook_response(row, include_secret=False).model_dump(
                mode="json"
            )
        else:
            if not await service.delete_webhook(change.id):
                raise OptionalBusinessError("not_found", "Webhook unavailable")
            result = {}
        await ctx.db.commit()
        return result


async def raw_update_hook(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
    return await _change_hook(ctx, _Update.model_validate(payload))


async def raw_delete_hook(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
    return await _change_hook(ctx, _Key.model_validate(payload))


def _guest(name: str) -> object:
    async def handler(
        ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
    ) -> dict[str, Any]:
        from plugins.business.automation.guest import commands
        from src.host.operations.business_guest.loopback import call_in_guest

        return await call_in_guest(ctx, getattr(commands, name), payload, progress)

    return handler


read_events = _guest("read_events")
event_types = _guest("event_types")
list_hooks = _guest("list_hooks")
create_hook = _guest("create_hook")
update_hook = _guest("update_hook")
delete_hook = _guest("delete_hook")


TENANT_AUTOMATION_OPERATIONS = {
    "app.automation.events.read": read_events,
    "app.automation.events.types": event_types,
    "app.automation.webhooks.read": list_hooks,
    "app.automation.webhooks.create": create_hook,
    "app.automation.webhooks.update": update_hook,
    "app.automation.webhooks.delete": delete_hook,
}
