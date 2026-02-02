"""
V2 SQLAlchemy implementation of WorkflowPatternRepository using BaseRepository.

This is a migrated version that:
- Extends BaseRepository for common CRUD operations
- Implements WorkflowPatternRepositoryPort interface
- Maintains 100% compatibility with original implementation
- Uses standard _to_domain() and _to_db() conversion methods

Migration Benefits:
- ~70% reduction in boilerplate code
- Consistent error handling via BaseRepository
- Built-in transaction management
- Bulk operations support
- Optional caching support via CachedRepositoryMixin (future)

Key Features:
- Tenant-level scoping (FR-019)
- JSON storage for pattern steps and metadata
- Increment usage count operation
- Ordering by usage_count and created_at
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.workflow_pattern import PatternStep, WorkflowPattern
from src.domain.ports.repositories.workflow_pattern_repository import WorkflowPatternRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import WorkflowPattern as DBPattern

logger = logging.getLogger(__name__)


class V2SqlWorkflowPatternRepository(BaseRepository[WorkflowPattern, DBPattern], WorkflowPatternRepositoryPort):
    """
    V2 SQLAlchemy implementation of WorkflowPatternRepository using BaseRepository.

    Leverages the base class for standard CRUD operations while providing
    workflow pattern-specific query methods.
    """

    # Define the SQLAlchemy model class
    _model_class = DBPattern

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session)

    # === Interface implementation (pattern-specific operations) ===

    async def create(self, pattern: WorkflowPattern) -> WorkflowPattern:
        """Create a new workflow pattern."""
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
        return await self.find_by_id(pattern_id)

    async def update(self, pattern: WorkflowPattern) -> WorkflowPattern:
        """Update an existing pattern."""
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
        """
        Delete a pattern by ID.

        Args:
            pattern_id: Pattern ID to delete

        Raises:
            ValueError: If pattern not found
        """
        result = await self._session.execute(select(DBPattern).where(DBPattern.id == pattern_id))
        db_pattern = result.scalar_one_or_none()

        if not db_pattern:
            raise ValueError(f"Pattern not found: {pattern_id}")

        await self._session.delete(db_pattern)
        await self._session.flush()

    async def list_by_tenant(
        self,
        tenant_id: str,
    ) -> List[WorkflowPattern]:
        """
        List all patterns for a tenant.

        Orders by usage_count desc, then created_at desc.

        Args:
            tenant_id: Tenant ID

        Returns:
            List of patterns
        """
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
        """
        Find a pattern by name within a tenant.

        Args:
            tenant_id: Tenant ID
            name: Pattern name

        Returns:
            Pattern or None
        """
        result = await self._session.execute(
            select(DBPattern)
            .where(DBPattern.tenant_id == tenant_id)
            .where(DBPattern.name == name)
        )

        db_pattern = result.scalar_one_or_none()

        return self._to_domain(db_pattern)

    async def increment_usage_count(
        self,
        pattern_id: str,
    ) -> WorkflowPattern:
        """
        Increment the usage count for a pattern.

        Args:
            pattern_id: Pattern ID

        Returns:
            Updated pattern

        Raises:
            ValueError: If pattern not found
        """
        pattern = await self.get_by_id(pattern_id)
        if not pattern:
            raise ValueError(f"Pattern not found: {pattern_id}")

        # Create updated pattern with incremented count
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

    # === Step conversion helpers ===

    def _step_to_dict(self, step: PatternStep) -> dict:
        """
        Convert a PatternStep to dictionary for JSON storage.

        Args:
            step: PatternStep to convert

        Returns:
            Dictionary representation
        """
        return {
            "step_number": step.step_number,
            "description": step.description,
            "tool_name": step.tool_name,
            "expected_output_format": step.expected_output_format,
            "similarity_threshold": step.similarity_threshold,
            "tool_parameters": step.tool_parameters,
        }

    def _step_from_dict(self, data: dict) -> PatternStep:
        """
        Convert a dictionary to PatternStep.

        Args:
            data: Dictionary data

        Returns:
            PatternStep instance
        """
        return PatternStep(
            step_number=data["step_number"],
            description=data["description"],
            tool_name=data["tool_name"],
            expected_output_format=data.get("expected_output_format", "text"),
            similarity_threshold=data.get("similarity_threshold", 0.8),
            tool_parameters=data.get("tool_parameters"),
        )

    # === Conversion methods ===

    def _to_domain(self, db_pattern: Optional[DBPattern]) -> Optional[WorkflowPattern]:
        """
        Convert database model to domain model.

        Args:
            db_pattern: Database model instance or None

        Returns:
            Domain model instance or None
        """
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

    def _to_db(self, domain_entity: WorkflowPattern) -> DBPattern:
        """
        Convert domain entity to database model.

        Args:
            domain_entity: Domain model instance

        Returns:
            Database model instance
        """
        return DBPattern(
            id=domain_entity.id,
            tenant_id=domain_entity.tenant_id,
            name=domain_entity.name,
            description=domain_entity.description,
            steps_json=[self._step_to_dict(s) for s in domain_entity.steps],
            success_rate=domain_entity.success_rate,
            usage_count=domain_entity.usage_count,
            metadata_json=domain_entity.metadata,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )
