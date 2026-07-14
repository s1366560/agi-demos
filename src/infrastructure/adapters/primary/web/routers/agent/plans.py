"""Plan Mode + Task List API endpoints.

Simple mode switch for Plan Mode (read-only analysis) vs Build Mode (full execution).
Task list endpoint for agent-managed task checklists per conversation.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import exists, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_db,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as ConversationModel,
    Project as ProjectModel,
    UserProject as UserProjectModel,
    UserTenant as UserTenantModel,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])


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
    status: str
    priority: str
    order_index: int
    created_at: str
    updated_at: str


class LegacyPlanApprovalCapability(BaseModel):
    kind: Literal["legacy_mode_switch"] = "legacy_mode_switch"


class TaskListResponse(BaseModel):
    conversation_id: str
    tasks: list[TaskItemResponse]
    total_count: int
    approval: LegacyPlanApprovalCapability


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

        priority_order = {"high": 0, "medium": 1, "low": 2}
        tasks.sort(key=lambda t: (priority_order.get(t.priority.value, 1), t.order_index))

        return TaskListResponse(
            conversation_id=conversation_id,
            tasks=[
                TaskItemResponse(
                    id=t.id,
                    conversation_id=t.conversation_id,
                    content=t.content,
                    status=t.status.value,
                    priority=t.priority.value,
                    order_index=t.order_index,
                    created_at=t.created_at.isoformat() if t.created_at else "",
                    updated_at=t.updated_at.isoformat() if t.updated_at else "",
                )
                for t in tasks
            ],
            total_count=len(tasks),
            approval=LegacyPlanApprovalCapability(),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting tasks")
        raise HTTPException(status_code=500, detail=_("Failed to get tasks")) from exc
