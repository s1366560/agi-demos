"""Plan Mode + Task List API endpoints.

Simple mode switch for Plan Mode (read-only analysis) vs Build Mode (full execution).
Task list endpoint for agent-managed task checklists per conversation.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.configuration.factories import create_llm_client
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_db,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentPlanVersionModel,
    Conversation as ConversationModel,
    Project as ProjectModel,
    UserProject as UserProjectModel,
    UserTenant as UserTenantModel,
    WorkspaceAgentPolicyModel,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)
_PLAN_RUN_TASKS: set[asyncio.Task[None]] = set()

router = APIRouter(prefix="/plan", tags=["plan"])
approval_router = APIRouter(prefix="/plans", tags=["plan"])


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
    environment: dict[str, Any] = Field(default_factory=dict)


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
            or existing.plan_version_id != body.plan_version_id
            or existing.message_id != body.message_id
            or existing.request_message != body.message
        ):
            raise HTTPException(status_code=409, detail=_("Plan approval idempotency conflict"))
        plan = await db.get(AgentPlanVersionModel, existing.plan_version_id)
        if plan is None:
            raise HTTPException(status_code=409, detail=_("Approved plan version is missing"))
        return _approval_response(conversation, plan, existing, created=False)

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

    policy = (
        await db.get(WorkspaceAgentPolicyModel, conversation.workspace_id)
        if conversation.workspace_id
        else None
    )
    permission_profile = {
        "ask": "read_only",
        "automatic": "workspace_write",
        "full_access": "full_access",
    }.get(policy.permission_mode if policy else "ask", "read_only")
    now = datetime.now(UTC)
    policy_snapshot = {
        "revision": policy.revision if policy else 0,
        "roles": dict(policy.roles_json) if policy else {},
        "fallbacks": list(policy.fallbacks_json) if policy else [],
        "reasoning_effort": policy.reasoning_effort if policy else "medium",
        "permission_mode": policy.permission_mode if policy else "ask",
    }
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
            "conversation_id": conversation.id,
            "project_id": conversation.project_id,
            "plan_version_id": plan.id,
            "mode": "build",
            "policy": policy_snapshot,
            "permission_profile": permission_profile,
            "environment": body.environment,
        },
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.commit()
    response = _approval_response(conversation, plan, run, created=True)
    base_container = cast(DIContainer, request.app.state.container)
    task = asyncio.create_task(
        _execute_approved_plan(
            base_container=base_container,
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


async def _execute_approved_plan(
    *,
    base_container: DIContainer,
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
        try:
            run.status = "running"
            run.updated_at = datetime.now(UTC)
            await session.commit()
            container = base_container.with_db(session)
            llm = await create_llm_client(tenant_id)
            service = container.agent_service(llm)
            async for _event in service.stream_chat_v2(
                conversation_id=conversation_id,
                user_message=message,
                project_id=project_id,
                user_id=user_id,
                tenant_id=tenant_id,
                execution_message_id=message_id,
            ):
                pass
            run.status = "ready_review"
            run.revision += 1
            completed_at = datetime.now(UTC)
            run.completed_at = completed_at
            run.updated_at = completed_at
            await session.commit()
        except Exception as exc:
            logger.exception("Approved plan execution failed: run_id=%s", run_id)
            await session.rollback()
            failed = await session.get(AgentPlanRunModel, run_id)
            if failed is not None:
                failed.status = "failed"
                failed.revision += 1
                failed.error = str(exc)[:2000]
                completed_at = datetime.now(UTC)
                failed.completed_at = completed_at
                failed.updated_at = completed_at
                await session.commit()
