"""
SQLAlchemy implementation of PlanRepository.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.plan import Plan, PlanDocumentStatus
from src.domain.ports.repositories.plan_repository import PlanRepository
from src.infrastructure.adapters.secondary.persistence.models import Conversation as DBConversation
from src.infrastructure.adapters.secondary.persistence.models import PlanDocument as DBPlanDocument

logger = logging.getLogger(__name__)


class SqlPlanRepository(PlanRepository):
    """SQLAlchemy implementation of PlanRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, plan: Plan) -> None:
        """Save a plan using PostgreSQL upsert (ON CONFLICT DO UPDATE)."""
        values = {
            "id": plan.id,
            "conversation_id": plan.conversation_id,
            "title": plan.title,
            "content": plan.content,
            "status": plan.status.value,
            "version": plan.version,
            "metadata_json": plan.metadata,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        }

        stmt = (
            pg_insert(DBPlanDocument)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "title": plan.title,
                    "content": plan.content,
                    "status": plan.status.value,
                    "version": plan.version,
                    "metadata_json": plan.metadata,
                    "updated_at": plan.updated_at,
                },
            )
        )

        await self._session.execute(stmt)
        await self._session.flush()

    async def find_by_id(self, plan_id: str) -> Optional[Plan]:
        """Find a plan by its ID."""
        result = await self._session.execute(
            select(DBPlanDocument).where(DBPlanDocument.id == plan_id)
        )
        db_plan = result.scalar_one_or_none()
        return self._to_domain(db_plan) if db_plan else None

    async def find_by_conversation_id(
        self,
        conversation_id: str,
        status: Optional[PlanDocumentStatus] = None,
    ) -> List[Plan]:
        """Find all plans for a conversation."""
        query = select(DBPlanDocument).where(DBPlanDocument.conversation_id == conversation_id)

        if status:
            query = query.where(DBPlanDocument.status == status.value)

        query = query.order_by(desc(DBPlanDocument.created_at))

        result = await self._session.execute(query)
        db_plans = result.scalars().all()
        return [self._to_domain(p) for p in db_plans]

    async def find_active_by_conversation(
        self,
        conversation_id: str,
    ) -> Optional[Plan]:
        """Find the active (non-archived) plan for a conversation."""
        result = await self._session.execute(
            select(DBPlanDocument)
            .where(DBPlanDocument.conversation_id == conversation_id)
            .where(DBPlanDocument.status != PlanDocumentStatus.ARCHIVED.value)
            .order_by(desc(DBPlanDocument.created_at))
            .limit(1)
        )
        db_plan = result.scalar_one_or_none()
        return self._to_domain(db_plan) if db_plan else None

    async def list_by_project(
        self,
        project_id: str,
        status: Optional[PlanDocumentStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Plan]:
        """List plans for a project (across all conversations)."""
        # Join with conversations to filter by project
        query = (
            select(DBPlanDocument)
            .join(DBConversation, DBPlanDocument.conversation_id == DBConversation.id)
            .where(DBConversation.project_id == project_id)
        )

        if status:
            query = query.where(DBPlanDocument.status == status.value)

        query = query.order_by(desc(DBPlanDocument.created_at)).offset(offset).limit(limit)

        result = await self._session.execute(query)
        db_plans = result.scalars().all()
        return [self._to_domain(p) for p in db_plans]

    async def list_by_user(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Plan]:
        """List plans created by a user."""
        query = (
            select(DBPlanDocument)
            .join(DBConversation, DBPlanDocument.conversation_id == DBConversation.id)
            .where(DBConversation.user_id == user_id)
        )

        if project_id:
            query = query.where(DBConversation.project_id == project_id)

        query = query.order_by(desc(DBPlanDocument.created_at)).offset(offset).limit(limit)

        result = await self._session.execute(query)
        db_plans = result.scalars().all()
        return [self._to_domain(p) for p in db_plans]

    async def delete(self, plan_id: str) -> None:
        """Delete a plan by ID."""
        await self._session.execute(delete(DBPlanDocument).where(DBPlanDocument.id == plan_id))
        await self._session.flush()

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all plans for a conversation."""
        await self._session.execute(
            delete(DBPlanDocument).where(DBPlanDocument.conversation_id == conversation_id)
        )
        await self._session.flush()

    async def count_by_conversation(self, conversation_id: str) -> int:
        """Count plans for a conversation."""
        result = await self._session.execute(
            select(func.count())
            .select_from(DBPlanDocument)
            .where(DBPlanDocument.conversation_id == conversation_id)
        )
        return result.scalar() or 0

    async def update_content(
        self,
        plan_id: str,
        content: str,
    ) -> Optional[Plan]:
        """Update plan content and increment version."""
        # First, get current version
        plan = await self.find_by_id(plan_id)
        if not plan:
            return None

        new_version = plan.version + 1
        now = datetime.now(timezone.utc)

        await self._session.execute(
            update(DBPlanDocument)
            .where(DBPlanDocument.id == plan_id)
            .values(
                content=content,
                version=new_version,
                updated_at=now,
            )
        )
        await self._session.flush()

        return await self.find_by_id(plan_id)

    async def update_status(
        self,
        plan_id: str,
        status: PlanDocumentStatus,
    ) -> Optional[Plan]:
        """Update plan status."""
        now = datetime.now(timezone.utc)

        await self._session.execute(
            update(DBPlanDocument)
            .where(DBPlanDocument.id == plan_id)
            .values(
                status=status.value,
                updated_at=now,
            )
        )
        await self._session.flush()

        return await self.find_by_id(plan_id)

    @staticmethod
    def _to_domain(db_plan: DBPlanDocument) -> Plan:
        """Convert database model to domain model."""
        return Plan(
            id=db_plan.id,
            conversation_id=db_plan.conversation_id,
            title=db_plan.title,
            content=db_plan.content,
            status=PlanDocumentStatus(db_plan.status),
            version=db_plan.version,
            metadata=db_plan.metadata_json or {},
            created_at=db_plan.created_at,
            updated_at=db_plan.updated_at or db_plan.created_at,
        )
