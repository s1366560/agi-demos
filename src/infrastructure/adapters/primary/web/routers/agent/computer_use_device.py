"""Native-vault authenticated claims for exactly one cloud tool invocation."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.chat_permission_admission_v2 import (
    PERMISSION_PROFILES,
    load_chat_permission_policy,
    require_chat_permission_mode,
)
from src.application.services.peer_chat_permission_validation_v2 import (
    require_peer_sender_permission_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentRunAuthorityModel,
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
from src.infrastructure.agent.native_computer_use.effects import validate_registered_call
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, request_key
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

from .computer_use_steps import router as execution_steps_router
from .run_authority_common import _load_scoped_run

router = APIRouter()


class ResumeAuthorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=256)


def broker_from_request(request: Request) -> NativeComputerBroker:
    redis = request.app.state.container.redis_client
    if redis is None:
        raise HTTPException(status_code=503, detail=_("Computer Use transport unavailable"))
    return NativeComputerBroker(redis)


async def require_project_access(
    db: AsyncSession, user_id: str, tenant_id: str, project_id: str
) -> None:
    allowed = await db.scalar(
        select(Project.id).where(
            Project.id == project_id,
            Project.tenant_id == tenant_id,
            exists(
                select(UserProject.id).where(
                    UserProject.user_id == user_id, UserProject.project_id == project_id
                )
            ),
            exists(
                select(UserTenant.id).where(
                    UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id
                )
            ),
            exists(select(User.id).where(User.id == user_id, User.is_active.is_(True))),
        )
    )
    if allowed is None:
        raise DeviceBridgeError("computer_use_scope_denied")


@router.get("/device/status")
async def device_status(
    request: Request,
    device_id: str,
    tenant_id: str,
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await require_project_access(db, current_user.id, tenant_id, project_id)
        devices = await broker_from_request(request).devices.list(
            user_id=current_user.id, tenant_id=tenant_id, project_id=project_id
        )
    except DeviceBridgeError as exc:
        raise HTTPException(status_code=403, detail=_("Computer Use device access denied")) from exc
    return {
        "ready": any(d["device_id"] == device_id and d["tool_definitions"] for d in devices),
        "device_id": device_id,
        "user_id": current_user.id,
        "tenant_id": tenant_id,
        "project_id": project_id,
    }


def validate_run_identity(
    run: AgentRunAuthorityModel, value: dict[str, Any], *, live_child: bool = False
) -> None:
    allowed_statuses = {"queued", "running"} | (
        {"completed", "ready_review"} if live_child else set()
    )
    if (
        run.status not in allowed_statuses
        or run.revision != value["authorization_revision"]
        or run.permission_profile != value["permission_profile"]
        or run.run_kind != value.get("run_kind", "chat")
        or run.plan_version_id != value["plan_version_id"]
        or run.tenant_id != value["tenant_id"]
        or run.project_id != value["project_id"]
        or run.conversation_id != value["conversation_id"]
        or run.authorization_snapshot.get("cancellation_receipt")
    ):
        raise DeviceBridgeError("computer_use_run_authority_changed")


async def require_child_owner(db: AsyncSession, value: dict[str, Any]) -> bool:
    child_id = value.get("child_run_id")
    if child_id is None:
        if value.get("child_owner_digest") is not None:
            raise DeviceBridgeError("computer_use_child_authority_invalid")
        return False
    from src.infrastructure.adapters.secondary.persistence.subagent_owner_model_v2 import (
        SubAgentOwnerLeaseV2,
    )
    from src.infrastructure.adapters.secondary.persistence.subagent_run_snapshot_model_v2 import (
        SubAgentRunSnapshotV2,
    )
    from src.infrastructure.agent.subagent.owner_lease_v2 import database_now_v2

    owner = await db.get(
        SubAgentOwnerLeaseV2, (value["conversation_id"], child_id), populate_existing=True
    )
    snapshot = await db.get(SubAgentRunSnapshotV2, value["conversation_id"], populate_existing=True)
    child = snapshot.runs.get(child_id) if snapshot is not None else None
    if (
        owner is None
        or owner.state != "active"
        or not owner.owner_token
        or owner.expires_at <= await database_now_v2(db)
        or hashlib.sha256(owner.owner_token.encode()).hexdigest() != value.get("child_owner_digest")
        or snapshot is None
        or snapshot.tenant_id != value["tenant_id"]
        or snapshot.project_id != value["project_id"]
        or not isinstance(child, dict)
        or child.get("status") not in {"pending", "running"}
    ):
        raise DeviceBridgeError("computer_use_child_authority_revoked")
    metadata = child.get("metadata")
    if not isinstance(metadata, dict):
        raise DeviceBridgeError("computer_use_child_authority_invalid")
    if value.get("run_kind", "chat") == "chat":
        mode = metadata.get("chat_permission_mode")
        valid_binding = (
            metadata.get("chat_permission_run_id") == value["run_id"]
            and not metadata.get("approved_plan_run_id")
            and isinstance(mode, str)
            and PERMISSION_PROFILES.get(mode) == value["permission_profile"]
        )
    else:
        valid_binding = (
            metadata.get("approved_plan_run_id") == value["run_id"]
            and not metadata.get("chat_permission_run_id")
            and metadata.get("approved_plan_permission_ceiling") == value["permission_profile"]
        )
    if not valid_binding:
        raise DeviceBridgeError("computer_use_child_parent_authority_changed")
    return True


async def current_call_effect(
    broker: NativeComputerBroker, value: dict[str, Any], *, allow_step_only: bool = False
) -> str:
    devices = await broker.devices.list(
        user_id=value["user_id"], tenant_id=value["tenant_id"], project_id=value["project_id"]
    )
    device = next(
        (
            d
            for d in devices
            if d["device_id"] == value["device_id"]
            and d["connection_id"] == value["connection_id"]
            and d["tool_definitions"]
        ),
        None,
    )
    if device is None:
        raise DeviceBridgeError("computer_use_device_disconnected")
    return validate_registered_call(device, value, allow_step_only=allow_step_only)


async def require_current_mcp_agent(db: AsyncSession, value: dict[str, Any]) -> None:
    if value.get("mcp_binding") is not None:
        from .computer_use_steps import current_agent_servers

        current_servers = await current_agent_servers(db, value, value["tool_name"])
        if tuple(value.get("allowed_mcp_servers", ())) != current_servers:
            raise DeviceBridgeError("computer_use_agent_authority_changed")


async def require_request_authority(
    db: AsyncSession,
    broker: NativeComputerBroker,
    value: dict[str, Any],
    user_id: str,
    *,
    resume: bool = False,
    allow_step_only: bool = False,
) -> None:
    """Recheck current run, workspace, child and catalog before native authority."""
    effect = await current_call_effect(broker, value, allow_step_only=allow_step_only)
    await require_current_mcp_agent(db, value)
    run, conversation = await _load_scoped_run(db, run_id=value["run_id"], user_id=user_id)
    initial_workspace_id = conversation.workspace_id
    live_child = await require_child_owner(db, value)
    validate_run_identity(run, value, live_child=live_child)
    if resume and run.status != "running":
        raise DeviceBridgeError("computer_use_parent_run_not_running")
    snapshot = dict(run.authorization_snapshot)
    policy = await load_chat_permission_policy(conversation)
    if run.run_kind == "chat":
        mode = snapshot.get("effective_permission_mode")
        if (
            snapshot.get("source") != "chat_admission"
            or snapshot.get("schema_version") != 1
            or not isinstance(mode, str)
            or PERMISSION_PROFILES.get(mode) != run.permission_profile
            or snapshot.get("workspace_id") != conversation.workspace_id
        ):
            raise DeviceBridgeError("computer_use_run_authorization_invalid")
        require_chat_permission_mode(policy, mode)
    elif run.run_kind == "plan":
        source = await db.get(AgentPlanRunModel, run.plan_run_id)
        approval = snapshot.get("approval_request")
        approved = approval.get("request") if isinstance(approval, dict) else None
        if (
            source is None
            or source.id != run.id
            or source.status != run.status
            or source.conversation_id != run.conversation_id
            or source.project_id != run.project_id
            or source.plan_version_id != run.plan_version_id
            or source.permission_profile != run.permission_profile
            or source.authorization_snapshot.get("approval_request") != approval
            or not isinstance(approved, dict)
            or not isinstance(approval, dict)
            or approval.get("schema_version") != 1
            or approval.get("user_id") != user_id
            or approval.get("tenant_id") != run.tenant_id
            or approved.get("permission_profile") != run.permission_profile
            or approved.get("plan_version_id") != run.plan_version_id
            or approved.get("project_id") != run.project_id
            or approved.get("conversation_id") != run.conversation_id
        ):
            raise DeviceBridgeError("computer_use_run_authorization_invalid")
        permission_mode = policy.get("permission_mode")
        ceiling = (
            PERMISSION_PROFILES.get(permission_mode) if isinstance(permission_mode, str) else None
        )
        levels = {"read_only": 0, "workspace_write": 1, "full_access": 2}
        if ceiling not in levels or levels[run.permission_profile] > levels[ceiling]:
            raise DeviceBridgeError("computer_use_run_permission_denied")
    else:
        raise DeviceBridgeError("computer_use_run_authorization_invalid")
    await require_peer_sender_permission_v2(
        run,
        "conversation_progress"
        if effect == "execute"
        else ("read" if effect == "read" else "system_api"),
        (run.tenant_id, run.project_id, run.conversation_id, user_id),
        async_session_factory,
    )
    # Policy transport may wait. Re-read membership/revision under the run
    # row lock before a one-shot claim or explicit resume authority is issued.
    run, current_conversation = await _load_scoped_run(
        db, run_id=value["run_id"], user_id=user_id, lock=True
    )
    validate_run_identity(run, value, live_child=await require_child_owner(db, value))
    if resume and run.status != "running":
        raise DeviceBridgeError("computer_use_parent_run_not_running")
    if run.authorization_snapshot != snapshot:
        raise DeviceBridgeError("computer_use_run_authority_changed")
    if resume and (
        current_conversation.workspace_id != initial_workspace_id
        or await load_chat_permission_policy(current_conversation) != policy
    ):
        raise DeviceBridgeError("computer_use_workspace_authority_changed")
    await require_current_mcp_agent(db, value)
    if await current_call_effect(broker, value, allow_step_only=allow_step_only) != effect:
        raise DeviceBridgeError("computer_use_tool_effect_changed")


@router.post("/device/requests/{request_id}/claim")
async def claim_device_request(
    request_id: str,
    body: ClaimRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    broker = broker_from_request(request)
    try:
        value = await broker.read(request_key(request_id))
        if (
            value is None
            or value["user_id"] != current_user.id
            or value["device_id"] != body.device_id
        ):
            raise DeviceBridgeError("computer_use_request_access_denied")
        await require_request_authority(db, broker, value, current_user.id)
        return await broker.claim(request_id, user_id=current_user.id, device_id=body.device_id)
    except (DeviceBridgeError, RuntimeV2Error) as exc:
        raise HTTPException(
            status_code=409,
            detail=_("Computer Use request is unavailable or its authority changed"),
        ) from exc


def require_completed_resume_request(
    value: dict[str, Any] | None, body: ResumeAuthorityRequest, user_id: str
) -> dict[str, Any]:
    if (
        value is None
        or value.get("user_id") != user_id
        or value.get("device_id") != body.device_id
        or value.get("session_id") != body.session_id
        or value.get("status") != "completed"
        or value.get("cancelled") is True
        or value.get("is_error") is not False
    ):
        raise DeviceBridgeError("computer_use_resume_authority_unavailable")
    return value


@router.post("/device/requests/{request_id}/resume-authority")
async def resume_device_authority(
    request_id: str,
    body: ResumeAuthorityRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Permit an explicit native resume; never consume, extend or replay a call."""
    broker = broker_from_request(request)
    try:
        value = require_completed_resume_request(
            await broker.read(request_key(request_id)), body, current_user.id
        )
        await require_request_authority(db, broker, value, current_user.id, resume=True)
        current = require_completed_resume_request(
            await broker.read(request_key(request_id)), body, current_user.id
        )
        if current != value:
            raise DeviceBridgeError("computer_use_resume_authority_changed")
        # This short response is valid only for resuming the existing native
        # session. The invocation expiry and result remain untouched; later
        # tool calls still require a new one-shot claim.
        return {
            **{
                key: value[key]
                for key in (
                    "request_id",
                    "user_id",
                    "tenant_id",
                    "project_id",
                    "device_id",
                    "conversation_id",
                    "run_id",
                    "session_id",
                    "authorization_revision",
                )
            },
            "expires_at": int(time.time()) + 30,
        }
    except (DeviceBridgeError, RuntimeV2Error) as exc:
        raise HTTPException(
            status_code=409,
            detail=_("Computer Use request is unavailable or its authority changed"),
        ) from exc


router.include_router(execution_steps_router)
