"""Activity and run review commands."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any, Literal

from pydantic import ConfigDict, Field

from plugins.business.agent.backend.chat_operations import (
    ConversationInput,
    _canonical,
    _Input,
    _own_conversation,
)
from plugins.business.agent.guest.binding import CommandContext, CommandError, Progress, current


class ActivityView(_Input):
    view: Literal["items", "receipts"]


class ActivityReadEntry(_Input):
    model_config = ConfigDict(extra="forbid")
    entry_id: str = Field(min_length=1, max_length=255)
    entry_revision: int = Field(ge=0)
    read_at: datetime


class ReceiptUpdate(_Input):
    model_config = ConfigDict(extra="forbid")
    expected_authority_revision: int = Field(ge=0)
    entries: list[ActivityReadEntry] = Field(default_factory=list, max_length=500)


class RunDetail(_Input):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    view: Literal["summary", "changes"]
    scope: Literal["run", "turn", "session"] = "run"
    expected_revision: int = Field(default=1, ge=1)
    turn_id: str | None = Field(default=None, max_length=255)


async def activity(ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    data = ActivityView.model_validate(payload)
    path = "my-work" if data.view == "items" else "activity/read-state"
    result = await _canonical(ctx, "GET", path, project_route=True)
    principal = getattr(getattr(ctx, "user", None), "id", None) or current().user_id
    return {**result, "principal_id": principal}


async def mark_read(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    data = ReceiptUpdate.model_validate(payload)
    return await _canonical(
        ctx,
        "PUT",
        "activity/read-state",
        project_route=True,
        body=data.model_dump(mode="json"),
    )


async def latest_run(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    data = ConversationInput.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    result = await _canonical(ctx, "GET", f"conversations/{data.conversation_id}/latest-run")
    projection = result.get("latest_run")
    if projection:
        fields = await current().run_fields(projection["id"], data.conversation_id)
        projection.update(fields)
    return result


async def _run_conversation(run_id: str) -> str | None:
    return await current().run_conversation(run_id)


async def run_detail(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    data = RunDetail.model_validate(payload)
    conversation = await _run_conversation(data.run_id)
    if conversation is None:
        raise CommandError("forbidden", "run unavailable for this project")
    await _own_conversation(ctx, conversation)
    query: dict[str, str | int] = {}
    if data.view == "changes":
        query.update(scope=data.scope, expected_revision=data.expected_revision)
        if data.turn_id:
            query["turn_id"] = data.turn_id
    return await _canonical(ctx, "GET", f"runs/{data.run_id}/{data.view}", query=query)


ACTIVITY_OPERATIONS: dict[str, Any] = {}
