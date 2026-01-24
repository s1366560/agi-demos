"""
SQLAlchemy implementation of WorkflowPatternRepository (T084).

Provides persistence for workflow patterns with tenant-level scoping.
"""

import logging
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.workflow_pattern import PatternStep, WorkflowPattern
from src.domain.ports.repositories.workflow_pattern_repository import WorkflowPatternRepositoryPort

logger = logging.getLogger(__name__)


class SQLWorkflowPatternRepository(WorkflowPatternRepositoryPort):
    """
    SQLAlchemy implementation of WorkflowPatternRepository.

    Uses a JSON column to store pattern steps and metadata.
    Implements tenant-level scoping (FR-019).
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, pattern: WorkflowPattern) -> WorkflowPattern:
        """Create a new workflow pattern."""
        # Import here to avoid circular imports
        from src.infrastructure.adapters.secondary.persistence.models import (
            WorkflowPattern as DBPattern,
        )

        db_pattern = DBPattern(
            id=pattern.id,
            tenant_id=pattern.tenant_id,
            name=pattern.name,
            description=pattern.description,
            steps_json=[self._step_to_dict(s) for s in pattern.steps],
            success_rate=pattern.success_rate,
            usage_count=pattern.usage_count,
            metadata_json=pattern.metadata,
            created_at=pattern.created_at,
            updated_at=pattern.updated_at,
        )

        self._session.add(db_pattern)
        await self._session.flush()

        return pattern

    async def get_by_id(self, pattern_id: str) -> Optional[WorkflowPattern]:
        """Get a pattern by its ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            WorkflowPattern as DBPattern,
        )

        result = await self._session.execute(select(DBPattern).where(DBPattern.id == pattern_id))
        db_pattern = result.scalar_one_or_none()

        return self._to_domain(db_pattern) if db_pattern else None

    async def update(self, pattern: WorkflowPattern) -> WorkflowPattern:
        """Update an existing pattern."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            WorkflowPattern as DBPattern,
        )

        result = await self._session.execute(select(DBPattern).where(DBPattern.id == pattern.id))
        db_pattern = result.scalar_one_or_none()

        if not db_pattern:
            raise ValueError(f"Pattern not found: {pattern.id}")

        # Update fields
        db_pattern.name = pattern.name
        db_pattern.description = pattern.description
        db_pattern.steps_json = [self._step_to_dict(s) for s in pattern.steps]
        db_pattern.success_rate = pattern.success_rate
        db_pattern.usage_count = pattern.usage_count
        db_pattern.metadata_json = pattern.metadata
        db_pattern.updated_at = pattern.updated_at

        await self._session.flush()

        return pattern

    async def delete(self, pattern_id: str) -> None:
        """Delete a pattern by ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            WorkflowPattern as DBPattern,
        )

        result = await self._session.execute(delete(DBPattern).where(DBPattern.id == pattern_id))

        if result.rowcount == 0:
            raise ValueError(f"Pattern not found: {pattern_id}")

    async def list_by_tenant(
        self,
        tenant_id: str,
    ) -> List[WorkflowPattern]:
        """List all patterns for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            WorkflowPattern as DBPattern,
        )

        result = await self._session.execute(
            select(DBPattern)
            .where(DBPattern.tenant_id == tenant_id)
            .order_by(DBPattern.usage_count.desc(), DBPattern.created_at.desc())
        )

        db_patterns = result.scalars().all()

        return [self._to_domain(p) for p in db_patterns]

    async def find_by_name(
        self,
        tenant_id: str,
        name: str,
    ) -> Optional[WorkflowPattern]:
        """Find a pattern by name within a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            WorkflowPattern as DBPattern,
        )

        result = await self._session.execute(
            select(DBPattern).where(DBPattern.tenant_id == tenant_id).where(DBPattern.name == name)
        )

        db_pattern = result.scalar_one_or_none()

        return self._to_domain(db_pattern) if db_pattern else None

    async def increment_usage_count(
        self,
        pattern_id: str,
    ) -> WorkflowPattern:
        """Increment the usage count for a pattern."""
        pattern = await self.get_by_id(pattern_id)
        if not pattern:
            raise ValueError(f"Pattern not found: {pattern_id}")

        # Create updated pattern with incremented count
        from datetime import datetime, timezone

        updated_pattern = WorkflowPattern(
            id=pattern.id,
            tenant_id=pattern.tenant_id,
            name=pattern.name,
            description=pattern.description,
            steps=pattern.steps,
            success_rate=pattern.success_rate,
            usage_count=pattern.usage_count + 1,
            created_at=pattern.created_at,
            updated_at=datetime.now(timezone.utc),
            metadata=pattern.metadata,
        )

        return await self.update(updated_pattern)

    def _step_to_dict(self, step: PatternStep) -> dict:
        """Convert a PatternStep to dictionary for JSON storage."""
        return {
            "step_number": step.step_number,
            "description": step.description,
            "tool_name": step.tool_name,
            "expected_output_format": step.expected_output_format,
            "similarity_threshold": step.similarity_threshold,
            "tool_parameters": step.tool_parameters,
        }

    def _step_from_dict(self, data: dict) -> PatternStep:
        """Convert a dictionary to PatternStep."""
        return PatternStep(
            step_number=data["step_number"],
            description=data["description"],
            tool_name=data["tool_name"],
            expected_output_format=data.get("expected_output_format", "text"),
            similarity_threshold=data.get("similarity_threshold", 0.8),
            tool_parameters=data.get("tool_parameters"),
        )

    def _to_domain(self, db_pattern) -> Optional[WorkflowPattern]:
        """Convert database model to domain entity."""
        if db_pattern is None:
            return None

        steps = [self._step_from_dict(s) for s in (db_pattern.steps_json or [])]

        return WorkflowPattern(
            id=db_pattern.id,
            tenant_id=db_pattern.tenant_id,
            name=db_pattern.name,
            description=db_pattern.description,
            steps=steps,
            success_rate=db_pattern.success_rate,
            usage_count=db_pattern.usage_count,
            created_at=db_pattern.created_at,
            updated_at=db_pattern.updated_at,
            metadata=db_pattern.metadata_json,
        )
