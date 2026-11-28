"""Automation command shaping. Authorities stay on the host; public fields are chosen here."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from plugins.business.guest_runtime.binding import current
from src.infrastructure.i18n import gettext as _

_RUN_FIELDS = ("receipt_id", "run_id", "job_id", "job_revision", "status", "duplicate")


def _scope(ctx: object) -> None:
    if not ctx.scope.project_id or not ctx.scope.tenant_id:
        raise HTTPException(422, _("Expected a project playbook request"))


async def read_playbooks(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    if payload:
        raise HTTPException(422, _("Expected a project playbook request"))
    _scope(ctx)
    return await current().data("automation.playbooks", {})


async def read_verdicts(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    if payload:
        raise HTTPException(422, _("Expected a project playbook request"))
    _scope(ctx)
    raw = await current().data("automation.verdicts", {})
    return {
        "items": [
            {key: value for key, value in item.items() if key != "proposed_payload"}
            for item in raw["items"]
        ]
    }


async def schedules(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.automation.schedule_models import PageQuery

    PageQuery.model_validate(payload)
    if not ctx.scope.project_id:
        raise HTTPException(422, _("A project is required"))
    document = await current().data("automation.schedules.query", payload)
    return _without_secrets(document)


async def save_schedule(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.automation.schedule_models import ScheduleEdit

    ScheduleEdit.model_validate(payload)
    document = await current().data("automation.schedules.save", payload)
    return _without_secrets(document)


async def run_schedule(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.schedule_models import RunRevision

    RunRevision.model_validate(payload)
    raw = await current().data("automation.schedules.run", payload)
    receipt = raw["receipt"]
    return {key: receipt[key] for key in _RUN_FIELDS if key in receipt}


async def delete_schedule(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.schedule_models import Revision

    edit = Revision.model_validate(payload)
    await current().data("automation.schedules.delete", payload)
    return {"id": edit.job_id}


def _without_secrets(document: dict[str, Any]) -> dict[str, Any]:
    hidden = {"credentials_encrypted", "proposed_payload", "delivery_secret"}

    def walk(value: object) -> object:
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items() if key not in hidden}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    walked = walk(document)
    return walked if isinstance(walked, dict) else {}


async def list_patterns(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.pattern_models import ListPatterns

    ListPatterns.model_validate(payload)
    raw = await current().data("automation.patterns.list", payload)
    return raw["document"]


async def delete_pattern(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.pattern_models import DeletePattern

    query = DeletePattern.model_validate(payload)
    raw = await current().data("automation.patterns.delete", {"pattern_id": query.pattern_id})
    return raw["document"]


async def schedule_conversations(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    del ctx
    if payload:
        raise HTTPException(422, _("Unexpected schedule conversation filter"))
    raw = await current().data("automation.conversations.list", {})
    return {
        "items": [
            {"id": row["id"], "title": row["title"], "workspaceId": row["workspace_id"]}
            for row in raw["rows"]
        ]
    }


async def _tenant(name: str, payload: dict[str, Any], model: object) -> dict[str, Any]:
    if model is not None:
        model.model_validate(payload)
    raw = await current().data(name, payload)
    return _without_secrets(raw["document"])


async def read_events(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.tenant_models import _Events

    return await _tenant("automation.events.read", payload, _Events)


async def event_types(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.tenant_models import _Input

    return await _tenant("automation.events.types", payload, _Input)


async def list_hooks(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.tenant_models import _Input

    return await _tenant("automation.webhooks.read", payload, _Input)


async def create_hook(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.tenant_models import _Create

    return await _tenant("automation.webhooks.create", payload, _Create)


async def update_hook(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.tenant_models import _Update

    return await _tenant("automation.webhooks.update", payload, _Update)


async def delete_hook(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.automation.tenant_models import _Key

    return await _tenant("automation.webhooks.delete", payload, _Key)


OPERATIONS = {
    "app.automation.playbooks.read": read_playbooks,
    "app.automation.schedules.read": schedules,
    "app.automation.schedules.write": save_schedule,
    "app.automation.schedules.run": run_schedule,
    "app.automation.schedules.delete": delete_schedule,
    "app.automation.patterns.read": list_patterns,
    "app.automation.patterns.delete": delete_pattern,
    "app.automation.verdicts.read": read_verdicts,
    "app.automation.events.read": read_events,
    "app.automation.events.types": event_types,
    "app.automation.webhooks.read": list_hooks,
    "app.automation.webhooks.create": create_hook,
    "app.automation.webhooks.update": update_hook,
    "app.automation.webhooks.delete": delete_hook,
    "app.automation.conversations.read": schedule_conversations,
}
