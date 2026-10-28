"""Fresh run authority for each operation performed by a claimed device REPL."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.agent.native_computer_use.catalog import BROWSER_TOOLS, mcp_binding
from src.infrastructure.agent.native_computer_use.effects import validate_registered_call
from src.infrastructure.agent.native_computer_use.steps import ExecutionSteps
from src.infrastructure.agent.native_computer_use.store import (
    DeviceBridgeError,
    digest,
    request_key,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

router = APIRouter()


class StepTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=64)
    id: str = Field(min_length=1, max_length=2048)
    browser_id: str | None = Field(default=None, max_length=256)
    tab_id: str | int | None = None
    url: str | None = Field(default=None, max_length=8192)
    origin: str | None = Field(default=None, max_length=8192)
    current_url: str | None = Field(default=None, max_length=8192)


class StepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=256)
    cell_id: str = Field(min_length=1, max_length=256)
    tool_name: str = Field(min_length=1, max_length=256)
    input_json: str = Field(min_length=2, max_length=256 * 1024)
    target: StepTarget
    parent_request_id: str | None = Field(default=None, min_length=1, max_length=256)
    receipt: str | None = Field(default=None, min_length=1, max_length=256)
    outcome: Literal["not_sent"] | None = None


async def current_agent_servers(
    db: AsyncSession, parent: dict[str, Any], tool_name: str
) -> tuple[str, ...]:
    from src.infrastructure.adapters.secondary.persistence.models import Conversation
    from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
        SqlAgentRegistryRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.subagent_run_snapshot_model_v2 import (
        SubAgentRunSnapshotV2,
    )
    from src.infrastructure.agent.sisyphus.builtin_agent import DEFAULT_GENERAL_AGENT_ID

    agent_id = parent.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        raise DeviceBridgeError("computer_use_agent_authority_missing")
    conversation = await db.get(Conversation, parent["conversation_id"], populate_existing=True)
    if conversation is None or any(
        getattr(conversation, name) != parent[name]
        for name in ("user_id", "tenant_id", "project_id")
    ):
        raise DeviceBridgeError("computer_use_agent_authority_changed")
    child_id = parent.get("child_run_id")
    child = None
    if child_id is not None:
        snapshot = await db.get(
            SubAgentRunSnapshotV2, parent["conversation_id"], populate_existing=True
        )
        child = snapshot.runs.get(child_id) if snapshot is not None else None
        if (
            snapshot is None
            or snapshot.tenant_id != parent["tenant_id"]
            or snapshot.project_id != parent["project_id"]
            or not isinstance(child, dict)
            or child.get("status") not in {"pending", "running"}
        ):
            raise DeviceBridgeError("computer_use_child_authority_revoked")
    elif (
        (conversation.agent_config or {}).get("selected_agent_id") or DEFAULT_GENERAL_AGENT_ID
    ) != agent_id:
        raise DeviceBridgeError("computer_use_agent_authority_changed")
    agent = await SqlAgentRegistryRepository(db).get_by_id(
        agent_id, tenant_id=parent["tenant_id"], project_id=parent["project_id"]
    )
    if agent is None or not agent.enabled or agent.project_id not in (None, parent["project_id"]):
        raise DeviceBridgeError("computer_use_agent_authority_changed")
    if child is not None and child.get("subagent_name") != agent.name:
        raise DeviceBridgeError("computer_use_child_agent_changed")
    if not agent.has_tool_access(tool_name):
        raise DeviceBridgeError("computer_use_agent_tool_denied")
    return tuple(agent.allowed_mcp_servers)


@router.post("/device/requests/{request_id}/steps/{step_id}/authorize")
async def authorize_device_step(
    request_id: str,
    step_id: str,
    body: StepRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from .computer_use_device import broker_from_request, require_request_authority

    broker = broker_from_request(request)
    try:
        parent = await broker.read(request_key(request_id))
        if (
            parent is None
            or parent["user_id"] != current_user.id
            or parent["device_id"] != body.device_id
        ):
            raise DeviceBridgeError("computer_use_request_access_denied")
        await require_request_authority(db, broker, parent, current_user.id)
        devices = await broker.devices.list(
            user_id=current_user.id, tenant_id=parent["tenant_id"], project_id=parent["project_id"]
        )
        device = next(
            (
                d
                for d in devices
                if d["device_id"] == body.device_id
                and d["connection_id"] == parent["connection_id"]
            ),
            None,
        )
        if device is None:
            raise DeviceBridgeError("computer_use_device_disconnected")
        definition = next(
            (d for d in device["tool_definitions"] if d["name"] == body.tool_name), None
        )
        if definition is None:
            raise DeviceBridgeError("computer_use_tool_unavailable")
        allowed = await current_agent_servers(db, parent, body.tool_name)
        # This validates schema/effect/server scope while retaining a pending verdict.
        # The sole execute permit is the consumed receipt returned below.
        call = {
            **parent,
            "tool_name": body.tool_name,
            "input_json": body.input_json,
            "allowed_mcp_servers": allowed,
            "approved_tools": [body.tool_name],
        }
        call.pop("tool_effect", None)
        call["mcp_binding"] = definition["inputSchema"].get("x-cua-mcp-binding")
        effect = validate_registered_call(device, call, allow_step_only=True)
        await require_request_authority(db, broker, call, current_user.id, allow_step_only=True)
        if mcp_binding(definition["inputSchema"]) is not None and not parent.get("agent_id"):
            raise DeviceBridgeError("computer_use_agent_authority_missing")
        if body.tool_name in BROWSER_TOOLS and body.target.kind not in {"browser", "mcp_app"}:
            raise DeviceBridgeError("computer_use_step_target_invalid")
        arguments = json.loads(body.input_json)
        if not isinstance(arguments, dict):
            raise DeviceBridgeError("computer_use_invalid_params")
        # Re-read the canonical definition immediately before issuing/consuming a receipt.
        if await current_agent_servers(db, parent, body.tool_name) != allowed:
            raise DeviceBridgeError("computer_use_agent_authority_changed")
        payload = body.model_dump(exclude_none=True)
        return await ExecutionSteps(broker.redis).authorize(
            parent, step_id, payload, effect=effect, catalog_digest=digest(definition)
        )
    except (DeviceBridgeError, RuntimeV2Error, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=409, detail=_("Computer Use step is unavailable or its authority changed")
        ) from exc
