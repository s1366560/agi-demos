"""Tenant-bound commands delegating to the original dashboard authorities."""

from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from src.host.operations.device_conversations import ConversationId
from src.infrastructure.adapters.primary.web.routers import system
from src.infrastructure.adapters.primary.web.routers.agent import config, trace_router
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    UpdateTenantAgentConfigRequest,
)
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .chat_operations import Identifier

if TYPE_CHECKING:
    from src.host.operations.application_commands import (
        Operation,
        PackageOperationContext,
        Progress,
    )


class DashboardInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Read(DashboardInput):
    view: Literal["runs", "active", "config", "permission", "revision", "catalog", "system"]


class Trace(DashboardInput):
    conversation_id: ConversationId
    trace_id: Identifier


class Update(DashboardInput):
    config: UpdateTenantAgentConfigRequest
    expected_revision: int = Field(ge=1)


def _authority(ctx: "PackageOperationContext") -> dict[str, Any]:
    if getattr(ctx.scope, "project_id", None):
        raise OptionalBusinessError("forbidden", "Tenant installation required")
    return {"tenant_id": ctx.scope.tenant_id, "current_user": ctx.user, "db": ctx.db}


def _error(exc: HTTPException) -> OptionalBusinessError:
    code = {403: "forbidden", 404: "page_not_found", 409: "conflict", 422: "invalid_input"}
    return OptionalBusinessError(code.get(exc.status_code, "runtime_unavailable"), str(exc.detail))


async def read_dashboard(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    view = Read.model_validate(payload).view
    authority = _authority(ctx)
    data: BaseModel
    try:
        match view:
            case "runs":
                data = await trace_router.list_tenant_runs(
                    request=ctx.request, status=None, limit=20, **authority
                )
            case "active":
                data = await trace_router.get_tenant_active_run_count(
                    request=ctx.request, **authority
                )
            case "config":
                data = await config.get_tenant_agent_config(request=ctx.request, **authority)
            case "revision":
                data = await config.get_tenant_agent_config_authority_revision(
                    request=ctx.request, **authority
                )
            case "catalog":
                data = await config.get_hook_catalog(**authority)
            case "permission":
                return await config.check_config_modify_permission(**authority)
            case "system":
                return await system.get_system_info(ctx.user)
        return data.model_dump(mode="json")
    except HTTPException as exc:
        raise _error(exc) from exc


async def inspect_trace(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    item = Trace.model_validate(payload)
    authority = _authority(ctx)
    belongs = await ctx.db.scalar(
        select(Conversation.id).where(
            Conversation.id == item.conversation_id,
            Conversation.tenant_id == authority["tenant_id"],
        )
    )
    if belongs is None:
        raise OptionalBusinessError("page_not_found", "Conversation unavailable")
    try:
        trace = await trace_router.get_trace_chain(
            item.conversation_id, item.trace_id, ctx.request, None, ctx.user, ctx.db
        )
        return trace.model_dump(mode="json")
    except HTTPException as exc:
        raise _error(exc) from exc


async def update_dashboard(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    item = Update.model_validate(payload)
    try:
        result = await config.update_tenant_agent_config(
            item.config, ctx.request, expected_revision=item.expected_revision, **_authority(ctx)
        )
        return {"status": 200, "config": result.model_dump(mode="json")}
    except HTTPException as exc:
        if exc.status_code == 409:
            return {"status": 409}
        raise _error(exc) from exc


DASHBOARD_OPERATIONS: dict[str, "Operation"] = {
    "app.agent.dashboard.read": read_dashboard,
    "app.agent.dashboard.trace": inspect_trace,
    "app.agent.dashboard.configure": update_dashboard,
}
