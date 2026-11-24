"""Read the fields shown by the workspace directory from scoped Workspace Core routes."""

import asyncio
import json
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.i18n import gettext as _

from .workspace_directory_export import _body, _request_core, read_workspace_operation

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2


class SummaryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary_for: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class Card(BaseModel):
    tenant_id: str
    project_id: str
    created_by: str
    id: str
    name: str
    office_status: str
    is_archived: bool
    description: str | None = None
    created_at: str
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def directory_card(card: Card, scope: "ScopeBindingV2") -> dict[str, Any]:
    if (card.tenant_id, card.project_id) != (scope.tenant_id, scope.project_id):
        raise HTTPException(403, _("Workspace directory scope mismatch"))
    data = card.model_dump(exclude={"metadata"})
    data["metadata"] = {
        key: value
        for key in (
            "workspace_use_case",
            "workspace_type",
            "collaboration_mode",
            "agent_conversation_mode",
            "sandbox_code_root",
        )
        if isinstance(value := card.metadata.get(key), str)
    }
    context = card.metadata.get("code_context")
    if isinstance(context, dict) and isinstance(root := context.get("sandbox_code_root"), str):
        data["metadata"]["code_context"] = {"sandbox_code_root": root}
    return data


async def directory_summary(ctx: "PackageOperationContext", query: SummaryQuery) -> dict[str, Any]:
    workspace = query.summary_for
    await read_workspace_operation(ctx, {"workspace_id": workspace}, None)

    async def read(child: str) -> object:
        try:
            upstream = await _request_core(
                ctx,
                workspace=workspace,
                child=(child,),
                task_route=child != "objectives",
                query=b"outbox_limit=0&event_limit=0&include_details=false&recover_stale_attempts=false"
                if child == "plan"
                else b"",
            )
            try:
                if upstream.status_code == 200:
                    return json.loads(await _body(upstream))
            finally:
                await upstream.aclose()
        except (HTTPException, ValueError):
            return None
        return None

    def rows(value: object, key: str) -> list[dict[str, Any]] | None:
        items = value.get(key) if isinstance(value, dict) else value
        if not isinstance(items, list) or any(
            not isinstance(item, dict) or item.get("workspace_id", workspace) != workspace
            for item in items
        ):
            return None
        return items

    objectives, plan = await asyncio.gather(read("objectives"), read("plan"))
    items = rows(objectives, "items")
    nodes = plan.get("plan") if isinstance(plan, dict) else None
    node_items = rows(nodes, "nodes") if isinstance(nodes, dict) else None
    root = plan.get("root_goal") if isinstance(plan, dict) else None
    tasks = None if items or node_items else rows(await read("tasks"), "items")
    return {
        "objectives": None
        if items is None
        else [
            {"obj_type": item.get("obj_type"), "progress": item.get("progress")} for item in items
        ],
        "plan": None
        if not isinstance(plan, dict)
        else {
            "root_goal": {"status": root.get("status")} if isinstance(root, dict) else None,
            "plan": {
                "nodes": [
                    {"kind": node.get("kind"), "intent": node.get("intent")} for node in node_items
                ]
            }
            if node_items is not None
            else None,
        },
        "tasks": None if tasks is None else [{"status": task.get("status")} for task in tasks],
    }
