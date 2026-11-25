"""Project activity receipts and run review delegated to the authenticated canonical API."""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field
from sqlalchemy import select

from src.application.schemas.activity_read_state import UpdateActivityReadStateRequest
from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .chat_operations import ConversationInput, Identifier, _canonical, _Input, _own_conversation

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class ActivityView(_Input):
    view: Literal["items", "receipts"]


class ReceiptUpdate(UpdateActivityReadStateRequest):
    expected_authority_revision: int = Field(ge=0)


class RunDetail(_Input):
    run_id: Identifier
    view: Literal["summary", "changes"]
    scope: Literal["run", "turn", "session"] = "run"
    expected_revision: int = Field(default=1, ge=1)
    turn_id: str | None = Field(default=None, max_length=255)


async def activity(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = ActivityView.model_validate(payload)
    path = "my-work" if data.view == "items" else "activity/read-state"
    result = await _canonical(ctx, "GET", path, project_route=True)
    return {**result, "principal_id": ctx.user.id}


async def mark_read(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = ReceiptUpdate.model_validate(payload)
    return await _canonical(
        ctx, "PUT", "activity/read-state", project_route=True, body=data.model_dump(mode="json")
    )


async def latest_run(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = ConversationInput.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    result = await _canonical(ctx, "GET", f"conversations/{data.conversation_id}/latest-run")
    projection = result.get("latest_run")
    if projection:
        run = await ctx.db.scalar(
            select(AgentRunAuthorityModel).where(
                AgentRunAuthorityModel.id == projection["id"],
                AgentRunAuthorityModel.conversation_id == data.conversation_id,
                AgentRunAuthorityModel.tenant_id == ctx.scope.tenant_id,
                AgentRunAuthorityModel.project_id == ctx.scope.project_id,
            )
        )
        if run is None:
            raise OptionalBusinessError("forbidden", "run unavailable for this project")
        projection.update(
            permission_profile=run.permission_profile,
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            error=run.error,
        )
    return result


async def run_detail(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = RunDetail.model_validate(payload)
    conversation = await ctx.db.scalar(
        select(AgentRunAuthorityModel.conversation_id).where(
            AgentRunAuthorityModel.id == data.run_id,
            AgentRunAuthorityModel.tenant_id == ctx.scope.tenant_id,
            AgentRunAuthorityModel.project_id == ctx.scope.project_id,
        )
    )
    if conversation is None:
        raise OptionalBusinessError("forbidden", "run unavailable for this project")
    await _own_conversation(ctx, conversation)
    query: dict[str, str | int] = {}
    if data.view == "changes":
        query.update(scope=data.scope, expected_revision=data.expected_revision)
        if data.turn_id:
            query["turn_id"] = data.turn_id
    return await _canonical(ctx, "GET", f"runs/{data.run_id}/{data.view}", query=query)


ACTIVITY_OPERATIONS = {
    "app.agent.activity.read": activity,
    "app.agent.activity.receipts": mark_read,
    "app.agent.review.latest": latest_run,
    "app.agent.review.details": run_detail,
}
