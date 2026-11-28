"""Raw host data for business guests.

These calls use the admitted actor. They do not apply the command's public projection.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

type Progress = Callable[[dict[str, Any]], Awaitable[None]]


async def invoke_data(
    ctx: object, name: str, params: dict[str, Any], progress: Progress | None
) -> dict[str, Any]:
    handler = _DATA.get(name)
    if handler is None:
        raise OptionalBusinessError("forbidden", "unknown host data")
    return await handler(ctx, params, progress)


async def _core(ctx: object, params: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    from plugins.business.workspace.backend.workspace_directory_export import core_document

    return await core_document(ctx, params)


async def _file_chunks(
    ctx: object, params: dict[str, Any], progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.workspace.backend.board_file_transfer import raw_file_chunks

    return await raw_file_chunks(ctx, params["workspace"], params["file_id"], progress)


async def _file_upload(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.workspace.backend.board_file_transfer import upload

    return await upload(
        ctx,
        params["workspace"],
        params["operation"],
        UUID(params["request_id"]),
        params["revision"],
        params.get("fields") or {},
    )


async def _memory_rows(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.project_memory_operation import raw_memory_rows

    return await raw_memory_rows(ctx, params)


async def _memory_record(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.package_memory_editor import raw_memory_record

    return await raw_memory_record(ctx, params["id"])


async def _memory_exists(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.package_memory_editor import _require_memory

    await _require_memory(ctx, params["id"])
    return {"found": True}


async def _memory_commands(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.memory_workbench import _legacy_commands

    return {"commands": await _legacy_commands(ctx, params["rows"])}


async def _draft_read(
    ctx: object, _params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.memory_drafts import read_draft

    return await read_draft(ctx)


async def _draft_write(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.memory_drafts import write_draft_document

    await write_draft_document(ctx, params["document"])
    return {"saved": True}


async def _task_visible(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.memory_maintenance import task_is_visible

    await task_is_visible(ctx, params["id"])
    return {"id": params["id"]}


async def _verdicts(
    ctx: object, _params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.playbook_operation import raw_verdicts

    return await raw_verdicts(ctx)


async def _playbooks(
    ctx: object, _params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.playbook_operation import raw_playbooks

    return await raw_playbooks(ctx)


async def _schedules(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.schedule_operations import raw_schedules

    return await raw_schedules(ctx, params)


async def _save_schedule(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.schedule_operations import raw_save_schedule

    return await raw_save_schedule(ctx, params)


async def _run_schedule(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.schedule_operations import raw_run_schedule

    return await raw_run_schedule(ctx, params)


async def _delete_schedule(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.schedule_operations import raw_delete_schedule

    return await raw_delete_schedule(ctx, params)


async def _conversations(
    ctx: object, _params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.schedule_conversations import (
        raw_schedule_conversations,
    )

    return await raw_schedule_conversations(ctx)


async def _patterns_list(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.pattern_operations import raw_list_patterns

    return await raw_list_patterns(ctx, params)


async def _patterns_delete(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.automation.backend.pattern_operations import raw_delete_pattern

    return await raw_delete_pattern(ctx, params["pattern_id"])


async def _tenant_document(module_name: str, ctx: object, params: dict[str, Any]) -> dict[str, Any]:
    from plugins.business.automation.backend import tenant_automation_operations as ops

    document = await getattr(ops, module_name)(ctx, params)
    return {"document": document}


async def _events(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    return await _tenant_document("raw_read_events", ctx, params)


async def _event_types(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    return await _tenant_document("raw_event_types", ctx, params)


async def _hooks(ctx: object, params: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    return await _tenant_document("raw_list_hooks", ctx, params)


async def _create_hook(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    return await _tenant_document("raw_create_hook", ctx, params)


async def _update_hook(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    return await _tenant_document("raw_update_hook", ctx, params)


async def _delete_hook(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    return await _tenant_document("raw_delete_hook", ctx, params)


async def _sandbox(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.package_sandbox_operations import _request

    method = str(params["method"])
    suffix = str(params["suffix"])
    body = params.get("body")
    if body is None and not params.get("absent_ok"):
        document = await _request(ctx, method, suffix)
    elif params.get("absent_ok"):
        document = await _request(ctx, method, suffix, body, absent_ok=True)
    else:
        document = await _request(ctx, method, suffix, body)
    return {"document": document}


async def _terminal(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.interaction_channel import open_run_terminal

    return await open_run_terminal(ctx, params["session_id"], params["resume_token"])


async def _channel(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.interaction_channel import _exchange

    return await _exchange(ctx, params["payload"], params["kind"])


async def _write_cluster(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.cluster_operations import raw_write_cluster

    return await raw_write_cluster(ctx, params)


async def _delete_cluster(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.cluster_operations import raw_delete_cluster

    return await raw_delete_cluster(ctx, params["id"])


async def _runner_list(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.cluster_runner_operations import raw_list_pools

    return await raw_list_pools(ctx, params)


async def _runner_create(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.cluster_runner_operations import raw_create_pool

    return await raw_create_pool(ctx, params)


async def _runner_token(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.cluster_runner_operations import raw_issue_token

    return await raw_issue_token(ctx, params)


async def _deploys_read(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.deploy_operations import raw_read_deploys

    return await raw_read_deploys(ctx, params)


async def _deploys_write(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.deploy_operations import raw_change_deploy

    return await raw_change_deploy(ctx, params)


async def _templates_read(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.instance_template_operations import (
        raw_read_templates,
    )

    return await raw_read_templates(ctx, params)


async def _templates_write(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.instance_template_operations import (
        raw_change_template,
    )

    return await raw_change_template(ctx, params)


async def _instance_access(
    ctx: object, _params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.instance_template_operations import (
        raw_instance_access,
    )

    return await raw_instance_access(ctx)


async def _instance_cluster(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.instance_template_operations import raw_cluster_owned

    return await raw_cluster_owned(ctx, params["id"])


async def _instance_create(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.instance_template_operations import (
        raw_create_instance,
    )

    return await raw_create_instance(ctx, params)


async def _inventory(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.environments.backend.inventory_operations import raw_inventory

    return await raw_inventory(ctx, params)


async def _account(
    ctx: object, params: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    from plugins.business.billing.backend.account_operations import raw_account_parts

    return await raw_account_parts(ctx, bool(params.get("full_history")))


async def _plan(ctx: object, params: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    from plugins.business.billing.backend.account_operations import raw_change_plan

    return await raw_change_plan(ctx, params)


_DATA = {
    "workspace.core": _core,
    "workspace.file.chunks": _file_chunks,
    "workspace.file.upload": _file_upload,
    "knowledge.memories.rows": _memory_rows,
    "knowledge.memory.record": _memory_record,
    "knowledge.memory.exists": _memory_exists,
    "knowledge.memory.commands": _memory_commands,
    "knowledge.draft.read": _draft_read,
    "knowledge.draft.write": _draft_write,
    "knowledge.task.visible": _task_visible,
    "automation.verdicts": _verdicts,
    "automation.playbooks": _playbooks,
    "automation.schedules.query": _schedules,
    "automation.schedules.save": _save_schedule,
    "automation.schedules.run": _run_schedule,
    "automation.schedules.delete": _delete_schedule,
    "automation.conversations.list": _conversations,
    "automation.patterns.list": _patterns_list,
    "automation.patterns.delete": _patterns_delete,
    "automation.events.read": _events,
    "automation.events.types": _event_types,
    "automation.webhooks.read": _hooks,
    "automation.webhooks.create": _create_hook,
    "automation.webhooks.update": _update_hook,
    "automation.webhooks.delete": _delete_hook,
    "environments.sandbox.exchange": _sandbox,
    "environments.terminal.open": _terminal,
    "environments.channel": _channel,
    "environments.clusters.write": _write_cluster,
    "environments.clusters.delete": _delete_cluster,
    "environments.runners.list": _runner_list,
    "environments.runners.create": _runner_create,
    "environments.runners.token": _runner_token,
    "environments.deploys.read": _deploys_read,
    "environments.deploys.write": _deploys_write,
    "environments.templates.read": _templates_read,
    "environments.templates.write": _templates_write,
    "environments.instances.access": _instance_access,
    "environments.instances.cluster": _instance_cluster,
    "environments.instances.create": _instance_create,
    "environments.inventory.read": _inventory,
    "billing.account.parts": _account,
    "billing.plan.apply": _plan,
}
