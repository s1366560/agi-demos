"""
V2 SQLAlchemy implementation of ToolCompositionRepositoryPort using BaseRepository.
"""

import logging
from typing import Any, Optional, cast

from sqlalchemy import Select, delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import ToolComposition
from src.domain.ports.repositories.tool_composition_repository import ToolCompositionRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    ToolComposition as DBToolComposition,
)

logger = logging.getLogger(__name__)


class SqlToolCompositionRepository(
    BaseRepository[ToolComposition, DBToolComposition], ToolCompositionRepositoryPort
):
    """V2 SQLAlchemy implementation of ToolCompositionRepositoryPort using BaseRepository."""

    _model_class = DBToolComposition

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save(self, composition: "ToolComposition") -> "ToolComposition":
        """Save a tool composition."""

        result = await self._session.execute(
            refresh_select_statement(
                self._refresh_statement(
                    select(DBToolComposition).where(DBToolComposition.id == composition.id)
                )
            )
        )
        db_composition = result.scalar_one_or_none()

        composition_data = {
            "tenant_id": composition.tenant_id,
            "project_id": composition.project_id,
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

        result_domain = self._to_domain(db_composition)
        assert result_domain is not None  # db_composition was just refreshed
        return result_domain

    async def get_by_id(
        self,
        composition_id: str,
        tenant_id: str | None = None,
    ) -> Optional["ToolComposition"]:
        """Get a tool composition by its ID."""
        statement = select(DBToolComposition).where(DBToolComposition.id == composition_id)
        if tenant_id:
            statement = statement.where(DBToolComposition.tenant_id == tenant_id)

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(statement))
        )
        db_composition = result.scalar_one_or_none()
        return self._to_domain(db_composition) if db_composition else None

    async def get_by_name(
        self,
        name: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> Optional["ToolComposition"]:
        """Get a tool composition by its name."""
        statement = select(DBToolComposition).where(DBToolComposition.name == name)
        statement = self._apply_scope(statement, tenant_id=tenant_id, project_id=project_id)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(statement))
        )
        db_compositions = list(result.scalars().all())
        db_composition = self._prefer_project_match(db_compositions, project_id=project_id)
        return self._to_domain(db_composition) if db_composition else None

    async def list_by_tools(
        self,
        tool_names: list[str],
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list["ToolComposition"]:
        """List tool compositions that use the specified tools."""
        statement = self._apply_scope(
            select(DBToolComposition),
            tenant_id=tenant_id,
            project_id=project_id,
        )
        # Load all compositions and filter in Python
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(statement))
        )
        db_compositions = result.scalars().all()

        # Filter compositions that contain any of the specified tools
        matching_compositions = []
        tool_name_set = set(tool_names)
        for comp in db_compositions:
            comp_tools = comp.tools if comp.tools else []
            if tool_name_set.intersection(comp_tools):
                matching_compositions.append(comp)

        return [d for c in matching_compositions if (d := self._to_domain(c)) is not None]

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str | None = None,
        project_id: str | None = None,
        **filters: object,
    ) -> list["ToolComposition"]:
        """List all tool compositions."""
        statement = self._apply_scope(
            select(DBToolComposition),
            tenant_id=tenant_id,
            project_id=project_id,
        )
        result = await self._session.execute(
            refresh_select_statement(
                self._refresh_statement(
                    statement.order_by(DBToolComposition.usage_count.desc()).limit(limit)
                )
            )
        )
        db_compositions = result.scalars().all()
        return [d for c in db_compositions if (d := self._to_domain(c)) is not None]

    async def update_usage(
        self,
        composition_id: str,
        success: bool,
    ) -> Optional["ToolComposition"]:
        """Update composition usage statistics."""
        result = await self._session.execute(
            refresh_select_statement(
                self._refresh_statement(
                    select(DBToolComposition).where(DBToolComposition.id == composition_id)
                )
            )
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
            refresh_select_statement(
                self._refresh_statement(
                    delete(DBToolComposition).where(DBToolComposition.id == composition_id)
                )
            )
        )
        await self._session.flush()
        return cast(CursorResult[Any], result).rowcount > 0

    @staticmethod
    def _apply_scope(
        statement: Select[tuple[DBToolComposition]],
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> Select[tuple[DBToolComposition]]:
        """Apply optional tenant and project filters to a composition query."""
        if tenant_id:
            statement = statement.where(DBToolComposition.tenant_id == tenant_id)
        if project_id:
            statement = statement.where(
                (DBToolComposition.project_id == project_id)
                | (DBToolComposition.project_id.is_(None))
            )
        return statement

    @staticmethod
    def _prefer_project_match(
        db_compositions: list[DBToolComposition],
        project_id: str | None = None,
    ) -> DBToolComposition | None:
        """Prefer a project-scoped composition over a tenant-wide composition."""
        if not db_compositions:
            return None
        if project_id:
            for db_composition in db_compositions:
                if db_composition.project_id == project_id:
                    return db_composition
        for db_composition in db_compositions:
            if db_composition.project_id is None:
                return db_composition
        return db_compositions[0]

    @staticmethod
    def _to_domain(db_composition: DBToolComposition | None) -> ToolComposition | None:
        """Convert database model to domain model."""
        if db_composition is None:
            return None

        try:
            return ToolComposition(
                id=db_composition.id,
                tenant_id=db_composition.tenant_id,
                project_id=db_composition.project_id,
                name=db_composition.name,
                description=db_composition.description or "",
                tools=db_composition.tools if db_composition.tools else [],
                execution_template=db_composition.execution_template
                if db_composition.execution_template
                else {},
                success_count=db_composition.success_count,
                failure_count=db_composition.failure_count,
                usage_count=db_composition.usage_count,
                created_at=db_composition.created_at,
                updated_at=db_composition.updated_at or db_composition.created_at,
            )
        except ValueError as exc:
            logger.warning(
                "Skipping invalid tool composition %s: %s",
                db_composition.id,
                exc,
            )
            return None
