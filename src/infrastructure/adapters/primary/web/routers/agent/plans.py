"""Plan Mode + Task List API endpoints.

Simple mode switch for Plan Mode (read-only analysis) vs Build Mode (full execution).
Task list endpoint for agent-managed task checklists per conversation.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.agent.runtime_model_route import route_from_policy
from src.domain.model.auth.user import User
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_db,
)
from src.infrastructure.adapters.primary.web.routers.agent.approved_plan_stream import (
    consume_approved_plan_stream,
)
from src.infrastructure.adapters.primary.web.routers.agent.plan_approval_contract import (
    approval_request_identity,
    require_matching_approval_request,
    require_requested_permission_profile,
)
from src.infrastructure.adapters.primary.web.routers.workspace_agent_policy import (
    WorkspaceAgentPolicyResponse,
)
from src.infrastructure.adapters.primary.web.sandbox_application_authority_v2 import (
    sandbox_operation_authority_v2,
)
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.primary.web.workspace_core_runtime_resolver import (
    workspace_core_client_v2_from_request,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.event.redis_event_bus import RedisEventBusAdapter
from src.infrastructure.adapters.secondary.persistence.agent_run_settlement import (
    settle_agent_plan_run,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentRunAuthorityModel,
    Conversation as ConversationModel,
    HITLRequest,
    Project as ProjectModel,
    UserProject as UserProjectModel,
    UserTenant as UserTenantModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_plan_run_authority,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_turn_projection import current_agent_turn_service_v2
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    current_agent_worker_redis_client_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_agent_turn_operation_v2,
)
from src.infrastructure.workspace_core.client import WorkspaceCoreClientError

if TYPE_CHECKING:
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        ConnectionManager,
    )

logger = logging.getLogger(__name__)
_PLAN_RUN_TASKS: set[asyncio.Task[None]] = set()

router = APIRouter(prefix="/plan", tags=["plan"])
approval_router = APIRouter(prefix="/plans", tags=["plan"])


def get_connection_manager() -> "ConnectionManager":
    """Resolve the WebSocket manager lazily to keep router imports acyclic."""
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        get_connection_manager as resolve_connection_manager,
    )

    return resolve_connection_manager()


# === Request/Response Schemas ===


class SwitchModeRequest(BaseModel):
    conversation_id: str
    mode: Literal["plan", "build"]


class ModeResponse(BaseModel):
    conversation_id: str
    mode: str
    switched_at: str


class ConversationModeResponse(BaseModel):
    conversation_id: str
    mode: str


# === Endpoints ===


@router.post("/mode")
async def switch_mode(
    request_body: SwitchModeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModeResponse:
    """Switch conversation between Plan Mode (read-only) and Build Mode (full)."""
    try:
        await _require_owned_task_conversation(
            db,
            conversation_id=request_body.conversation_id,
            user_id=current_user.id,
        )
        stmt = (
            update(ConversationModel)
            .where(ConversationModel.id == request_body.conversation_id)
            .where(ConversationModel.user_id == current_user.id)
            .values(
                current_mode=request_body.mode,
                current_plan_id=None,
                updated_at=datetime.now(UTC),
            )
        )
        result = await db.execute(refresh_select_statement(stmt))
        await db.commit()

        if cast(CursorResult[Any], result).rowcount == 0:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        logger.info(
            f"Conversation {request_body.conversation_id} switched to "
            f"{request_body.mode} mode by user {current_user.id}"
        )

        return ModeResponse(
            conversation_id=request_body.conversation_id,
            mode=request_body.mode,
            switched_at=datetime.now(UTC).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error switching mode")
        raise HTTPException(status_code=500, detail=_("Failed to switch mode")) from exc


@router.get("/mode/{conversation_id}")
async def get_mode(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationModeResponse:
    """Get the current mode for a conversation."""
    try:
        await _require_owned_task_conversation(
            db,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )
        stmt = (
            select(ConversationModel.current_mode)
            .where(ConversationModel.id == conversation_id)
            .where(ConversationModel.user_id == current_user.id)
        )
        result = await db.execute(refresh_select_statement(stmt))
        mode = result.scalar_one_or_none()

        if mode is None:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        return ConversationModeResponse(
            conversation_id=conversation_id,
            mode=mode,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting mode")
        raise HTTPException(status_code=500, detail=_("Failed to get mode")) from exc


# === Task List Schemas ===


class TaskItemResponse(BaseModel):
    id: str
    conversation_id: str
    content: str
    title: str
    description: str | None = None
    estimated_duration_seconds: int | None = None
    started_at: str | None = None
    completed_at: str | None = None
    result_summary: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    status: str
    priority: str
    order_index: int
    created_at: str
    updated_at: str


class LegacyPlanApprovalCapability(BaseModel):
    kind: Literal["legacy_mode_switch"] = "legacy_mode_switch"


class PlanVersionResponse(BaseModel):
    id: str
    conversation_id: str
    version: int
    status: Literal["draft", "approved"]
    tasks: list[dict[str, Any]]
    created_at: str
    approved_at: str | None = None


class VersionedPlanApprovalCapability(BaseModel):
    kind: Literal["versioned_atomic"] = "versioned_atomic"
    plan_version: PlanVersionResponse


class TaskListResponse(BaseModel):
    conversation_id: str
    tasks: list[TaskItemResponse]
    total_count: int
    approval: LegacyPlanApprovalCapability | VersionedPlanApprovalCapability
    plan_version: PlanVersionResponse | None = None


class ApprovePlanEnvironmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["local", "worktree"]


class ApprovePlanAndStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    project_id: str
    plan_version_id: str
    expected_plan_version: int = Field(ge=1)
    permission_profile: Literal["read_only", "workspace_write", "full_access"]
    message: str = Field(min_length=1)
    message_id: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=255)
    environment: ApprovePlanEnvironmentRequest


async def _load_workspace_policy_snapshot(
    request: Request,
    *,
    conversation: ConversationModel,
    current_user: User,
) -> tuple[dict[str, Any], str]:
    workspace_id = conversation.workspace_id
    if not workspace_id:
        return (
            {
                "revision": 0,
                "roles": {},
                "fallbacks": [],
                "reasoning_effort": "medium",
                "permission_mode": "ask",
            },
            "read_only",
        )

    try:
        client = workspace_core_client_v2_from_request(request)
    except (RuntimeError, TypeError) as exc:
        raise workspace_core_unavailable_error() from exc
    path = (
        f"/api/v1/tenants/{conversation.tenant_id}/projects/{conversation.project_id}"
        f"/workspaces/{workspace_id}/agent-policy"
    )
    try:
        upstream = await client.proxy_request(
            method="GET",
            path=path,
            query=b"",
            body=b"",
            headers=[
                ("Accept", "application/json"),
                ("X-MemStack-Tenant-ID", conversation.tenant_id),
                ("X-MemStack-Project-ID", conversation.project_id),
                ("X-MemStack-Workspace-ID", workspace_id),
                ("X-MemStack-User-ID", str(current_user.id)),
                (
                    "X-MemStack-User-Is-Superuser",
                    "true" if bool(getattr(current_user, "is_superuser", False)) else "false",
                ),
            ],
        )
        payload = b"".join([chunk async for chunk in upstream.aiter_raw()])
        if upstream.status_code != 200:
            raise WorkspaceCoreClientError("Workspace Core policy read failed")
        policy = WorkspaceAgentPolicyResponse.model_validate_json(payload)
    except Exception as exc:
        if isinstance(exc, HTTPException) and exc.status_code == 503:
            raise
        raise workspace_core_unavailable_error() from exc
    if (
        policy.tenant_id != conversation.tenant_id
        or policy.project_id != conversation.project_id
        or policy.workspace_id != workspace_id
    ):
        raise workspace_core_unavailable_error()
    snapshot = {
        "revision": policy.revision,
        "roles": {
            role: target.model_dump() if target is not None else None
            for role, target in policy.roles.items()
        },
        "fallbacks": [target.model_dump() for target in policy.fallbacks],
        "reasoning_effort": policy.reasoning_effort,
        "permission_mode": policy.permission_mode,
    }
    permission_profile = {
        "ask": "read_only",
        "automatic": "workspace_write",
        "full_access": "full_access",
    }[policy.permission_mode]
    return snapshot, permission_profile


# === Task List Endpoints ===


async def _require_owned_task_conversation(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
) -> None:
    """Require conversation ownership plus active tenant and project membership."""
    statement = select(ConversationModel.id).where(
        ConversationModel.id == conversation_id,
        ConversationModel.user_id == user_id,
        exists(
            select(ProjectModel.id).where(
                ProjectModel.id == ConversationModel.project_id,
                ProjectModel.tenant_id == ConversationModel.tenant_id,
            )
        ),
        exists(
            select(UserProjectModel.id).where(
                UserProjectModel.project_id == ConversationModel.project_id,
                UserProjectModel.user_id == user_id,
            )
        ),
        exists(
            select(UserTenantModel.id).where(
                UserTenantModel.tenant_id == ConversationModel.tenant_id,
                UserTenantModel.user_id == user_id,
            )
        ),
    )
    result = await db.execute(refresh_select_statement(statement))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))


@router.get("/tasks/{conversation_id}")
async def get_tasks(
    conversation_id: str,
    status: str | None = Query(None, description="Filter by status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    """Get the task list for a conversation."""
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository import (
            SqlAgentTaskRepository,
        )

        await _require_owned_task_conversation(
            db,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )

        repo = SqlAgentTaskRepository(db)
        tasks = await repo.find_by_conversation(conversation_id, status=status)
        version_result = await db.execute(
            refresh_select_statement(
                select(AgentPlanVersionModel)
                .where(AgentPlanVersionModel.conversation_id == conversation_id)
                .order_by(AgentPlanVersionModel.version.desc())
                .limit(1)
            )
        )
        version = version_result.scalar_one_or_none()

        priority_order = {"high": 0, "medium": 1, "low": 2}
        tasks.sort(key=lambda t: (priority_order.get(t.priority.value, 1), t.order_index))

        return TaskListResponse(
            conversation_id=conversation_id,
            tasks=[
                TaskItemResponse(
                    id=t.id,
                    conversation_id=t.conversation_id,
                    content=t.content,
                    title=t.title,
                    description=t.description,
                    estimated_duration_seconds=t.estimated_duration_seconds,
                    started_at=t.started_at.isoformat() if t.started_at else None,
                    completed_at=t.completed_at.isoformat() if t.completed_at else None,
                    result_summary=t.result_summary,
                    evidence_refs=list(t.evidence_refs),
                    status=t.status.value,
                    priority=t.priority.value,
                    order_index=t.order_index,
                    created_at=t.created_at.isoformat() if t.created_at else "",
                    updated_at=t.updated_at.isoformat() if t.updated_at else "",
                )
                for t in tasks
            ],
            total_count=len(tasks),
            approval=(
                VersionedPlanApprovalCapability(plan_version=_plan_version_response(version))
                if version is not None
                else LegacyPlanApprovalCapability()
            ),
            plan_version=_plan_version_response(version) if version is not None else None,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting tasks")
        raise HTTPException(status_code=500, detail=_("Failed to get tasks")) from exc


async def _resolve_cloud_run_environment(
    *,
    project_id: str,
    tenant_id: str,
    kind: Literal["local", "worktree"],
    bound_at: datetime,
) -> dict[str, Any]:
    try:
        async with (
            async_session_factory() as sandbox_db,
            sandbox_operation_authority_v2(
                db=sandbox_db,
                operation_id=f"approved-plan-environment:{project_id}",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id=tenant_id,
                    project_id=project_id,
                ),
                identity={"tenant_id": tenant_id, "project_id": project_id},
                metadata={"kind": "approved-plan-environment"},
            ) as authority,
        ):
            info = await authority.services.lifecycle_service.ensure_sandbox_running(
                project_id=project_id,
                tenant_id=tenant_id,
            )
    except Exception as exc:
        logger.warning(
            "Failed to resolve approved run environment: has_project_id=%s error_type=%s",
            bool(project_id),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail=_("Execution environment is unavailable"),
        ) from exc

    if (
        info.project_id != project_id
        or info.tenant_id != tenant_id
        or not info.is_healthy
        or not info.sandbox_id.strip()
    ):
        raise HTTPException(
            status_code=409,
            detail=_("Execution environment authority changed"),
        )
    created_at = info.created_at or bound_at
    created_at = (
        created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at.astimezone(UTC)
    )
    return {
        "id": info.sandbox_id,
        "kind": kind,
        "label": info.sandbox_id,
        "workspace_path": "/workspace",
        "repository_root": None,
        "branch": None,
        "base_commit": None,
        "source_run_id": None,
        "created_at": created_at.isoformat(),
    }


@approval_router.post("/approve-and-start")
async def approve_plan_and_start(
    body: ApprovePlanAndStartRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _require_owned_task_conversation(
        db,
        conversation_id=body.conversation_id,
        user_id=current_user.id,
    )
    conversation_result = await db.execute(
        refresh_select_statement(
            select(ConversationModel)
            .where(
                ConversationModel.id == body.conversation_id,
                ConversationModel.project_id == body.project_id,
                ConversationModel.user_id == current_user.id,
            )
            .with_for_update()
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))

    request_identity = approval_request_identity(
        body.model_dump(mode="json"),
        tenant_id=conversation.tenant_id,
        user_id=str(current_user.id),
    )
    existing_result = await db.execute(
        refresh_select_statement(
            select(AgentPlanRunModel).where(
                AgentPlanRunModel.idempotency_key == body.idempotency_key
            )
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if (
            existing.conversation_id != body.conversation_id
            or existing.project_id != body.project_id
            or existing.plan_version_id != body.plan_version_id
            or existing.message_id != body.message_id
            or existing.request_message != body.message
        ):
            raise HTTPException(status_code=409, detail=_("Plan approval idempotency conflict"))
        require_matching_approval_request(
            (existing.authorization_snapshot or {}).get("approval_request"),
            request_identity,
            run_id=existing.id,
        )
        plan = await db.get(AgentPlanVersionModel, existing.plan_version_id)
        if plan is None:
            raise HTTPException(status_code=409, detail=_("Approved plan version is missing"))
        return _approval_response(conversation, plan, existing, created=False)

    if body.environment.kind != "local":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PLAN_ENVIRONMENT_UNSUPPORTED",
                "message": _("This runtime does not provide the requested execution environment"),
            },
        )

    plan_result = await db.execute(
        refresh_select_statement(
            select(AgentPlanVersionModel)
            .where(AgentPlanVersionModel.conversation_id == body.conversation_id)
            .order_by(AgentPlanVersionModel.version.desc())
            .limit(1)
            .with_for_update()
        )
    )
    plan = plan_result.scalar_one_or_none()
    if (
        plan is None
        or plan.id != body.plan_version_id
        or plan.version != body.expected_plan_version
        or plan.status != "draft"
    ):
        raise HTTPException(status_code=409, detail=_("Plan version conflict"))

    active_run = await db.scalar(
        select(AgentRunAuthorityModel.id)
        .where(
            AgentRunAuthorityModel.tenant_id == conversation.tenant_id,
            AgentRunAuthorityModel.project_id == conversation.project_id,
            AgentRunAuthorityModel.conversation_id == conversation.id,
            AgentRunAuthorityModel.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    pending_hitl = await db.scalar(
        select(HITLRequest.id)
        .where(
            HITLRequest.tenant_id == conversation.tenant_id,
            HITLRequest.project_id == conversation.project_id,
            HITLRequest.conversation_id == conversation.id,
            HITLRequest.status == "pending",
            HITLRequest.expires_at > datetime.now(UTC),
        )
        .limit(1)
    )
    if active_run is not None or pending_hitl is not None:
        raise HTTPException(
            status_code=409, detail=_("Conversation is not ready for plan approval")
        )

    policy_snapshot, permission_profile = await _load_workspace_policy_snapshot(
        request,
        conversation=conversation,
        current_user=current_user,
    )
    permission_profile = require_requested_permission_profile(
        body.permission_profile, permission_profile
    )
    model_route = (
        route_from_policy(
            policy_snapshot, (conversation.agent_config or {}).get("capability_mode", "")
        )
        if conversation.workspace_id
        else None
    )
    now = datetime.now(UTC)
    environment = await _resolve_cloud_run_environment(
        project_id=conversation.project_id,
        tenant_id=conversation.tenant_id,
        kind=body.environment.kind,
        bound_at=now,
    )
    plan.status = "approved"
    plan.policy_revision = policy_snapshot["revision"]
    plan.approved_at = now
    conversation.current_mode = "build"
    conversation.current_plan_id = plan.id
    conversation.updated_at = now
    run = AgentPlanRunModel(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        plan_version_id=plan.id,
        idempotency_key=body.idempotency_key,
        message_id=body.message_id,
        request_message=body.message,
        status="queued",
        revision=1,
        permission_profile=permission_profile,
        authorization_snapshot={
            "approval_request": request_identity,
            "conversation_id": conversation.id,
            "project_id": conversation.project_id,
            "plan_version_id": plan.id,
            "mode": "build",
            "policy": policy_snapshot,
            "permission_profile": permission_profile,
            "environment": environment,
            **(
                {
                    "model_route": {
                        "provider_id": model_route.provider_id,
                        "model_id": model_route.model_id,
                    }
                }
                if model_route
                else {}
            ),
        },
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    await ensure_plan_run_authority(
        db,
        run=run,
        tenant_id=conversation.tenant_id,
    )
    await db.commit()
    response = _approval_response(conversation, plan, run, created=True)
    task = asyncio.create_task(
        _execute_approved_plan(
            run_id=run.id,
            conversation_id=conversation.id,
            project_id=conversation.project_id,
            tenant_id=conversation.tenant_id,
            user_id=current_user.id,
            message=body.message,
            message_id=body.message_id,
        ),
        name=f"approved-plan-{run.id}",
    )
    _PLAN_RUN_TASKS.add(task)
    task.add_done_callback(_PLAN_RUN_TASKS.discard)
    return response


def _plan_version_response(version: AgentPlanVersionModel) -> PlanVersionResponse:
    return PlanVersionResponse(
        id=version.id,
        conversation_id=version.conversation_id,
        version=version.version,
        status=cast(Literal["draft", "approved"], version.status),
        tasks=list(version.tasks_json),
        created_at=version.created_at.isoformat(),
        approved_at=version.approved_at.isoformat() if version.approved_at else None,
    )


def _approval_response(
    conversation: ConversationModel,
    plan: AgentPlanVersionModel,
    run: AgentPlanRunModel,
    *,
    created: bool,
) -> dict[str, Any]:
    return {
        "queued": run.status in {"queued", "running"},
        "created": created,
        "conversation": {
            "id": conversation.id,
            "project_id": conversation.project_id,
            "tenant_id": conversation.tenant_id,
            "user_id": conversation.user_id,
            "title": conversation.title,
            "status": conversation.status,
            "message_count": conversation.message_count,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
            "summary": conversation.summary,
            "agent_config": conversation.agent_config,
            "metadata": conversation.meta,
            "conversation_mode": conversation.conversation_mode,
            "current_mode": conversation.current_mode,
            "workspace_id": conversation.workspace_id,
            "linked_workspace_task_id": conversation.linked_workspace_task_id,
            "participant_agents": conversation.participant_agents,
            "coordinator_agent_id": conversation.coordinator_agent_id,
            "focused_agent_id": conversation.focused_agent_id,
        },
        "plan_version": _plan_version_response(plan).model_dump(),
        "run": {
            "id": run.id,
            "conversation_id": run.conversation_id,
            "project_id": run.project_id,
            "plan_version_id": run.plan_version_id,
            "idempotency_key": run.idempotency_key,
            "message_id": run.message_id,
            "request_message": run.request_message,
            "status": run.status,
            "revision": run.revision,
            "created_at": run.created_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
            "started_at": None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "last_heartbeat_at": None,
            "error": run.error,
            "environment": run.authorization_snapshot.get("environment"),
            "permission_profile": run.permission_profile,
            "authorization_snapshot": run.authorization_snapshot,
        },
    }


async def _publish_plan_run_status(
    *,
    run: AgentPlanRunModel,
) -> None:
    """Publish terminal plan-run authority after its database commit."""

    emitted_at = datetime.now(UTC)
    payload = {
        "id": run.id,
        "conversation_id": run.conversation_id,
        "project_id": run.project_id,
        "plan_version_id": run.plan_version_id,
        "idempotency_key": run.idempotency_key,
        "message_id": run.message_id,
        "request_message": run.request_message,
        "status": run.status,
        "revision": run.revision,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "started_at": None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "last_heartbeat_at": None,
        "error": run.error,
        "environment": run.authorization_snapshot.get("environment"),
        "permission_profile": run.permission_profile,
        "authorization_snapshot": run.authorization_snapshot,
    }
    event = {
        "type": "run_status",
        "event_type": "run_status",
        "conversation_id": run.conversation_id,
        "payload": payload,
        "data": payload,
        "timestamp": emitted_at.isoformat(),
        "event_time_us": int(emitted_at.timestamp() * 1_000_000),
        "event_counter": 0,
    }

    redis_client = current_agent_worker_redis_client_v2()
    try:
        await RedisEventBusAdapter(redis_client).publish_to_stream(
            run.conversation_id,
            event,
        )
    except Exception:
        logger.exception(
            "Failed to persist plan run status event: run_id=%s status=%s revision=%s",
            run.id,
            run.status,
            run.revision,
        )
    try:
        await get_connection_manager().broadcast_to_conversation(
            run.conversation_id,
            event,
        )
    except Exception:
        logger.exception(
            "Failed to broadcast plan run status event: run_id=%s status=%s revision=%s",
            run.id,
            run.status,
            run.revision,
        )


async def _broadcast_approved_plan_message(
    conversation_id: str, message: dict[str, Any]
) -> None:
    """Discard the recipient count so the stream consumer sees Awaitable[None]."""
    await get_connection_manager().broadcast_to_conversation(conversation_id, message)


async def _execute_approved_plan(
    *,
    run_id: str,
    conversation_id: str,
    project_id: str,
    tenant_id: str,
    user_id: str,
    message: str,
    message_id: str,
) -> None:
    async with async_session_factory() as session:
        run = await session.get(AgentPlanRunModel, run_id)
        if run is None:
            return
        started_at = datetime.now(UTC)
        async with pin_agent_turn_operation_v2(
            operation_id=f"approved-plan:{run_id}",
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=conversation_id,
            services={
                OPERATION_DB_SESSION_SERVICE_V2: session,
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "project_id": project_id,
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "agent-turn",
                    "channel": "approved-plan",
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "message_id": message_id,
                },
            },
            force_process_host_lease=True,
        ):
            try:
                run.status = "running"
                run.updated_at = started_at
                await session.commit()
                await _publish_plan_run_status(run=run)
                service = await current_agent_turn_service_v2()
                agent_stream = cast(
                    AsyncGenerator[dict[str, Any], None],
                    service.stream_chat_v2(
                        conversation_id=conversation_id,
                        user_message=message,
                        project_id=project_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        execution_message_id=message_id,
                        canonical_run_id=run_id,
                    ),
                )
                terminal_status = await consume_approved_plan_stream(
                    agent_stream,
                    conversation_id=conversation_id,
                    broadcast=_broadcast_approved_plan_message,
                )
                await session.refresh(run)
                run.status = terminal_status
                run.revision += 1
                completed_at = datetime.now(UTC)
                run.completed_at = completed_at
                run.updated_at = completed_at
                await settle_agent_plan_run(
                    session,
                    run=run,
                    tenant_id=tenant_id,
                    started_at=started_at,
                    succeeded=terminal_status == "ready_review",
                    completed_at=completed_at,
                )
                await session.commit()
                await _publish_plan_run_status(run=run)
            except Exception as exc:
                logger.exception("Approved plan execution failed: run_id=%s", run_id)
                await session.rollback()
                failed = await session.get(AgentPlanRunModel, run_id)
                if failed is not None:
                    await session.refresh(failed)
                    failed.status = "failed"
                    failed.revision += 1
                    failed.error = str(exc)[:2000]
                    completed_at = datetime.now(UTC)
                    failed.completed_at = completed_at
                    failed.updated_at = completed_at
                    await settle_agent_plan_run(
                        session,
                        run=failed,
                        tenant_id=tenant_id,
                        started_at=started_at,
                        succeeded=False,
                        completed_at=completed_at,
                    )
                    await session.commit()
                    await _publish_plan_run_status(run=failed)
