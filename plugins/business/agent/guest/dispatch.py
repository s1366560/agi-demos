"""Map an admitted agent operation name onto a guest command."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from plugins.business.agent.backend import (
    activity_operations,
    chat_operations as chat,
    composer,
    composer_context,
    dashboard_operations,
    lifecycle_control,
    workbench,
)
from plugins.business.agent.guest.binding import CommandContext, CommandError, Progress

Handler = Callable[[Any, dict[str, Any], Progress | None], Awaitable[dict[str, Any]]]

OPERATIONS: dict[str, Handler] = {
    "app.agent.list": chat.list_conversations,
    "app.agent.create": chat.create,
    "app.agent.rename": chat.rename,
    "app.agent.history": chat.history,
    "app.agent.turn": chat.turn,
    "app.agent.cancel": chat.cancel,
    "app.agent.interactions": workbench.interactions,
    "app.agent.respond": workbench.respond,
    "app.agent.attachments": workbench.upload,
    "app.agent.attachments.turn": workbench.attached_turn,
    "app.agent.activity.read": activity_operations.activity,
    "app.agent.activity.receipts": activity_operations.mark_read,
    "app.agent.review.latest": activity_operations.latest_run,
    "app.agent.review.details": activity_operations.run_detail,
    "app.agent.dashboard.read": dashboard_operations.read_dashboard,
    "app.agent.dashboard.trace": dashboard_operations.inspect_trace,
    "app.agent.dashboard.configure": dashboard_operations.update_dashboard,
    "app.agent.composer.read": composer.read,
    "app.agent.composer.save": composer.save,
    "app.agent.composer.models": composer.models,
    "app.agent.composer.context": composer_context.project_context,
    "app.agent.composer.welcome": composer.welcome,
    "app.agent.lifecycle.control": lifecycle_control.control,
    "app.agent.voice.authorize": composer.authorize_voice,
    "app.agent.tenant.list": chat.list_conversations,  # replaced below
}


async def tenant_list(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.agent.guest.binding import current

    if current().project_id:
        raise CommandError("forbidden", "Tenant installation required")
    return await current().tenant_sessions("list", payload or {})


async def tenant_create(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.agent.guest.binding import current

    if current().project_id:
        raise CommandError("forbidden", "Tenant installation required")
    return await current().tenant_sessions("create", payload)


async def tenant_open(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.agent.guest.binding import current

    if current().project_id:
        raise CommandError("forbidden", "Tenant installation required")
    return await current().tenant_sessions("open", payload)


OPERATIONS["app.agent.tenant.list"] = tenant_list
OPERATIONS["app.agent.tenant.create"] = tenant_create
OPERATIONS["app.agent.tenant.open"] = tenant_open


TOOLS = {
    "agent.chat-list": "app.agent.list",
    "agent.chat-create": "app.agent.create",
    "agent.chat-history": "app.agent.history",
    "agent.chat-turn": "app.agent.turn",
    "agent.chat-cancel": "app.agent.cancel",
    "agent.chat-rename": "app.agent.rename",
    "agent.chat-interactions": "app.agent.interactions",
    "agent.chat-respond": "app.agent.respond",
    "agent.chat-upload": "app.agent.attachments",
    "agent.chat-attached-turn": "app.agent.attachments.turn",
    "agent.activity-list": "app.agent.activity.read",
    "agent.activity-mark": "app.agent.activity.receipts",
    "agent.review-latest": "app.agent.review.latest",
    "agent.review-details": "app.agent.review.details",
    "agent.dashboard-read": "app.agent.dashboard.read",
    "agent.dashboard-trace": "app.agent.dashboard.trace",
    "agent.dashboard-configure": "app.agent.dashboard.configure",
    "agent.chat-composer-read": "app.agent.composer.read",
    "agent.chat-composer-save": "app.agent.composer.save",
    "agent.chat-models": "app.agent.composer.models",
    "agent.chat-project-context": "app.agent.composer.context",
    "agent.chat-welcome": "app.agent.composer.welcome",
    "agent.chat-lifecycle-control": "app.agent.lifecycle.control",
    "agent.chat-voice-authorize": "app.agent.voice.authorize",
    "agent.tenant-session-list": "app.agent.tenant.list",
    "agent.tenant-session-create": "app.agent.tenant.create",
    "agent.tenant-session-open": "app.agent.tenant.open",
}
