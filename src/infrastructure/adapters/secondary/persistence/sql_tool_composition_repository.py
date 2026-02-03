"""
V2 SQLAlchemy implementation of ToolCompositionRepositoryPort using BaseRepository.
"""

import logging
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.tool_composition_repository import ToolCompositionRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    ToolComposition as DBToolComposition,
)

if TYPE_CHECKING:
    from src.domain.model.agent import ToolComposition

logger = logging.getLogger(__name__)


class SqlToolCompositionRepository(
    BaseRepository[object, DBToolComposition], ToolCompositionRepositoryPort
):
    """V2 SQLAlchemy implementation of ToolCompositionRepositoryPort using BaseRepository."""

    _model_class = DBToolComposition

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save(self, composition: "ToolComposition") -> "ToolComposition":
        """Save a tool composition."""

        result = await self._session.execute(
            select(DBToolComposition).where(DBToolComposition.id == composition.id)
        )
        db_composition = result.scalar_one_or_none()

        composition_data = {
            "name": composition.name,
            "description": composition.description,
            "tools": composition.tools if composition.tools else [],
            "execution_template": composition.execution_template
            if composition.execution_template
            else {},
            "success_count": composition.success_count,
            "failure_count": composition.failure_count,
            "usage_count": composition.usage_count,
        }

        if db_composition:
            # Update existing composition
            for key, value in composition_data.items():
                setattr(db_composition, key, value)
        else:
            # Create new composition
            db_composition = DBToolComposition(
                id=composition.id,
                created_at=composition.created_at,
                updated_at=composition.updated_at,
                **composition_data,
            )
            self._session.add(db_composition)

        await self._session.flush()
        await self._session.refresh(db_composition)

        return self._to_domain(db_composition)

    async def get_by_id(self, composition_id: str) -> Optional["ToolComposition"]:
        """Get a tool composition by its ID."""
        result = await self._session.execute(
            select(DBToolComposition).where(DBToolComposition.id == composition_id)
        )
        db_composition = result.scalar_one_or_none()
        return self._to_domain(db_composition) if db_composition else None

    async def get_by_name(self, name: str) -> Optional["ToolComposition"]:
        """Get a tool composition by its name."""
        result = await self._session.execute(
            select(DBToolComposition).where(DBToolComposition.name == name)
        )
        db_composition = result.scalar_one_or_none()
        return self._to_domain(db_composition) if db_composition else None

    async def list_by_tools(self, tool_names: List[str]) -> List["ToolComposition"]:
        """List tool compositions that use the specified tools."""
        # Load all compositions and filter in Python
        result = await self._session.execute(select(DBToolComposition))
        db_compositions = result.scalars().all()

        # Filter compositions that contain any of the specified tools
        matching_compositions = []
        tool_name_set = set(tool_names)
        for comp in db_compositions:
            comp_tools = comp.tools if comp.tools else []
            if tool_name_set.intersection(comp_tools):
                matching_compositions.append(comp)

        return [self._to_domain(c) for c in matching_compositions]

    async def list_all(self, limit: int = 100) -> List["ToolComposition"]:
        """List all tool compositions."""
        result = await self._session.execute(
            select(DBToolComposition).order_by(DBToolComposition.usage_count.desc()).limit(limit)
        )
        db_compositions = result.scalars().all()
        return [self._to_domain(c) for c in db_compositions]

    async def update_usage(
        self,
        composition_id: str,
        success: bool,
    ) -> Optional["ToolComposition"]:
        """Update composition usage statistics."""
        result = await self._session.execute(
            select(DBToolComposition).where(DBToolComposition.id == composition_id)
        )
        db_composition = result.scalar_one_or_none()

        if not db_composition:
            return None

        db_composition.usage_count += 1
        if success:
            db_composition.success_count += 1
        else:
            db_composition.failure_count += 1

        await self._session.flush()
        await self._session.refresh(db_composition)

        return self._to_domain(db_composition)

    async def delete(self, composition_id: str) -> bool:
        """Delete a tool composition."""
        result = await self._session.execute(
            delete(DBToolComposition).where(DBToolComposition.id == composition_id)
        )
        await self._session.flush()
        return result.rowcount > 0

    @staticmethod
    def _to_domain(db_composition: DBToolComposition) -> "ToolComposition":
        """Convert database model to domain model."""
        from src.domain.model.agent import ToolComposition

        return ToolComposition(
            id=db_composition.id,
            tenant_id="global",  # Tool compositions are global/shared
            name=db_composition.name,
            description=db_composition.description,
            tools=db_composition.tools if db_composition.tools else ["dummy"],  # Ensure non-empty
            execution_template=db_composition.execution_template
            if db_composition.execution_template
            else {},
            success_count=db_composition.success_count,
            failure_count=db_composition.failure_count,
            usage_count=db_composition.usage_count,
            created_at=db_composition.created_at,
            updated_at=db_composition.updated_at,
        )
