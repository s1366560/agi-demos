"""
V2 SQLAlchemy implementation of WorkPlanRepositoryPort using BaseRepository.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.work_plan_repository import WorkPlanRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import WorkPlan as DBWorkPlan

if TYPE_CHECKING:
    from src.domain.model.agent import WorkPlan

logger = logging.getLogger(__name__)


class SqlWorkPlanRepository(BaseRepository[object, DBWorkPlan], WorkPlanRepositoryPort):
    """V2 SQLAlchemy implementation of WorkPlanRepositoryPort using BaseRepository."""

    _model_class = DBWorkPlan

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save(self, plan: "WorkPlan") -> "WorkPlan":
        """Save a work plan."""

        result = await self._session.execute(select(DBWorkPlan).where(DBWorkPlan.id == plan.id))
        db_plan = result.scalar_one_or_none()

        plan_data = {
            "conversation_id": plan.conversation_id,
            "status": plan.status.value if hasattr(plan.status, "value") else plan.status,
            "steps": [s.to_dict() if hasattr(s, "to_dict") else s for s in plan.steps]
            if plan.steps
            else [],
            "current_step_index": plan.current_step_index,
            "workflow_pattern_id": plan.workflow_pattern_id,
        }

        if db_plan:
            # Update existing plan
            for key, value in plan_data.items():
                setattr(db_plan, key, value)
            db_plan.updated_at = datetime.utcnow()
        else:
            # Create new plan
            db_plan = DBWorkPlan(
                id=plan.id,
                created_at=plan.created_at,
                updated_at=plan.updated_at,
                **plan_data,
            )
            self._session.add(db_plan)

        await self._session.flush()

        return self._to_domain(db_plan)

    async def get_by_id(self, plan_id: str) -> Optional["WorkPlan"]:
        """Get a work plan by its ID."""

        result = await self._session.execute(select(DBWorkPlan).where(DBWorkPlan.id == plan_id))
        db_plan = result.scalar_one_or_none()
        return self._to_domain(db_plan) if db_plan else None

    async def get_by_conversation(self, conversation_id: str) -> List["WorkPlan"]:
        """Get all work plans for a conversation."""

        result = await self._session.execute(
            select(DBWorkPlan)
            .where(DBWorkPlan.conversation_id == conversation_id)
            .order_by(DBWorkPlan.created_at.desc())
        )
        db_plans = result.scalars().all()
        return [self._to_domain(p) for p in db_plans]

    async def get_active_by_conversation(self, conversation_id: str) -> Optional["WorkPlan"]:
        """Get the active (in-progress) work plan for a conversation."""
        from src.domain.model.agent import PlanStatus

        result = await self._session.execute(
            select(DBWorkPlan).where(
                DBWorkPlan.conversation_id == conversation_id,
                DBWorkPlan.status == PlanStatus.IN_PROGRESS,
            )
        )
        db_plan = result.scalar_one_or_none()
        return self._to_domain(db_plan) if db_plan else None

    async def delete(self, plan_id: str) -> bool:
        """Delete a work plan."""
        result = await self._session.execute(delete(DBWorkPlan).where(DBWorkPlan.id == plan_id))
        await self._session.flush()
        return result.rowcount > 0

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all work plans for a conversation."""
        await self._session.execute(
            delete(DBWorkPlan).where(DBWorkPlan.conversation_id == conversation_id)
        )
        await self._session.flush()

    @staticmethod
    def _to_domain(db_plan: DBWorkPlan) -> "WorkPlan":
        """Convert database model to domain model."""
        from src.domain.model.agent import PlanStatus, PlanStep, WorkPlan

        # Convert steps dict to PlanStep value objects
        steps = []
        if db_plan.steps:
            for step_dict in db_plan.steps:
                if isinstance(step_dict, dict):
                    steps.append(
                        PlanStep(
                            step_number=step_dict.get("step_number", 0),
                            description=step_dict.get("description", ""),
                            thought_prompt=step_dict.get("thought_prompt", ""),
                            required_tools=step_dict.get("required_tools", []),
                            expected_output=step_dict.get("expected_output", ""),
                            dependencies=step_dict.get("dependencies", []),
                        )
                    )
                else:
                    steps.append(step_dict)

        return WorkPlan(
            id=db_plan.id,
            conversation_id=db_plan.conversation_id,
            status=PlanStatus(db_plan.status)
            if isinstance(db_plan.status, str)
            else db_plan.status,
            steps=steps,
            current_step_index=db_plan.current_step_index,
            workflow_pattern_id=db_plan.workflow_pattern_id,
            created_at=db_plan.created_at,
            updated_at=db_plan.updated_at,
        )
