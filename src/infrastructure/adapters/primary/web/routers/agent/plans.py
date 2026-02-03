"""Plan mode endpoints for Agent API.

Provides endpoints for Plan Mode management:
- enter_plan_mode: Enter Plan Mode for a conversation
- exit_plan_mode: Exit Plan Mode
- get_plan: Get a plan by ID
- list_conversation_plans: List all plans for a conversation
- update_plan: Update a plan
- get_plan_mode_status: Get Plan Mode status for a conversation
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .schemas import (
    EnterPlanModeRequest,
    ExitPlanModeRequest,
    PlanModeStatusResponse,
    PlanResponse,
    UpdatePlanRequest,
)
from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_plan_response(plan) -> PlanResponse:
    """Convert domain Plan to PlanResponse."""
    return PlanResponse(
        id=plan.id,
        conversation_id=plan.conversation_id,
        title=plan.title,
        content=plan.content,
        status=plan.status.value,
        version=plan.version,
        metadata=plan.metadata,
        created_at=plan.created_at.isoformat(),
        updated_at=plan.updated_at.isoformat(),
    )


@router.post("/plan/enter", response_model=PlanResponse)
async def enter_plan_mode(
    data: EnterPlanModeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanResponse:
    """
    Enter Plan Mode for a conversation.

    Creates a new Plan document and switches the conversation to Plan Mode,
    which provides read-only access to the codebase plus plan editing capability.
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.enter_plan_mode_use_case()

        plan = await use_case.execute(
            conversation_id=data.conversation_id,
            title=data.title,
            description=data.description,
        )

        await db.commit()

        logger.info(
            f"User {current_user.id} entered Plan Mode for conversation {data.conversation_id}"
        )

        return _to_plan_response(plan)

    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        if "already in Plan Mode" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        logger.error(f"Error entering Plan Mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to enter Plan Mode: {str(e)}")


@router.post("/plan/exit", response_model=PlanResponse)
async def exit_plan_mode(
    data: ExitPlanModeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanResponse:
    """
    Exit Plan Mode for a conversation.

    Optionally approves the plan and returns to Build Mode.
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.exit_plan_mode_use_case()

        plan = await use_case.execute(
            conversation_id=data.conversation_id,
            plan_id=data.plan_id,
            approve=data.approve,
            summary=data.summary,
        )

        await db.commit()

        logger.info(
            f"User {current_user.id} exited Plan Mode for conversation {data.conversation_id}, "
            f"approved={data.approve}"
        )

        return _to_plan_response(plan)

    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        if "not in Plan Mode" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        logger.error(f"Error exiting Plan Mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to exit Plan Mode: {str(e)}")


@router.get("/plan/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanResponse:
    """
    Get a plan document by ID.
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.get_plan_use_case()

        plan = await use_case.execute(plan_id=plan_id)

        return _to_plan_response(plan)

    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        logger.error(f"Error getting plan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get plan: {str(e)}")


@router.get("/conversations/{conversation_id}/plans", response_model=list[PlanResponse])
async def list_conversation_plans(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> list[PlanResponse]:
    """
    List all plans for a conversation.
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.get_plan_use_case()

        plans = await use_case.get_by_conversation(conversation_id=conversation_id)

        return [_to_plan_response(plan) for plan in plans]

    except Exception as e:
        logger.error(f"Error listing plans: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list plans: {str(e)}")


@router.put("/plan/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: str,
    data: UpdatePlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanResponse:
    """
    Update a plan document.
    """
    try:
        container = get_container_with_db(request, db)
        use_case = container.update_plan_use_case()

        plan = await use_case.execute(
            plan_id=plan_id,
            content=data.content,
            title=data.title,
            explored_files=data.explored_files,
            critical_files=data.critical_files,
            metadata=data.metadata,
        )

        await db.commit()

        logger.info(f"User {current_user.id} updated plan {plan_id}")

        return _to_plan_response(plan)

    except Exception as e:
        await db.rollback()
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        if "cannot" in str(e).lower() or "invalid" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        logger.error(f"Error updating plan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update plan: {str(e)}")


@router.get("/conversations/{conversation_id}/plan-mode", response_model=PlanModeStatusResponse)
async def get_plan_mode_status(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> PlanModeStatusResponse:
    """
    Get the Plan Mode status for a conversation.
    """
    try:
        container = get_container_with_db(request, db)
        conversation_repo = container.conversation_repository()

        conversation = await conversation_repo.find_by_id(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get active plan if in Plan Mode
        plan_response: Optional[PlanResponse] = None
        if conversation.is_in_plan_mode and conversation.current_plan_id:
            plan_use_case = container.get_plan_use_case()
            try:
                plan = await plan_use_case.execute(plan_id=conversation.current_plan_id)
                plan_response = _to_plan_response(plan)
            except Exception:
                pass  # Plan might have been deleted

        return PlanModeStatusResponse(
            is_in_plan_mode=conversation.is_in_plan_mode,
            current_mode=conversation.current_mode.value,
            current_plan_id=conversation.current_plan_id,
            plan=plan_response,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plan mode status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get plan mode status: {str(e)}")
