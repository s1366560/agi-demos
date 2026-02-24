"""
V2 SQLAlchemy implementation of MemoryRepository using BaseRepository.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import Memory as DBMemory

logger = logging.getLogger(__name__)


class SqlMemoryRepository(BaseRepository[Memory, DBMemory], MemoryRepository):
    """V2 SQLAlchemy implementation of MemoryRepository using BaseRepository."""

    _model_class = DBMemory

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save(self, memory: Memory) -> None:
        """Save a memory (create or update)."""
        result = await self._session.execute(select(DBMemory).where(DBMemory.id == memory.id))
        db_memory = result.scalar_one_or_none()

        if db_memory:
            # Update existing memory
            db_memory.title = memory.title
            db_memory.content = memory.content
            db_memory.content_type = memory.content_type
            db_memory.tags = memory.tags
            db_memory.entities = memory.entities
            db_memory.relationships = memory.relationships
            db_memory.version = memory.version
            db_memory.collaborators = memory.collaborators
            db_memory.is_public = memory.is_public
            db_memory.status = memory.status
            db_memory.processing_status = memory.processing_status
            db_memory.meta = memory.metadata
            db_memory.updated_at = memory.updated_at  # type: ignore[assignment]
        else:
            # Create new memory
            db_memory = self._to_db(memory)
            self._session.add(db_memory)

        await self._session.flush()

    async def find_by_id(self, memory_id: str) -> Memory | None:
        """Find a memory by ID."""
        return await super().find_by_id(memory_id)

    async def list_by_project(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        """List all memories for a project."""
        return await self.list_all(limit=limit, offset=offset, project_id=project_id)

    async def delete(self, memory_id: str) -> None:
        """Delete a memory."""
        await super().delete(memory_id)

    def _to_domain(self, db_memory: DBMemory | None) -> Memory | None:
        """Convert database model to domain model."""
        if db_memory is None:
            return None

        return Memory(
            id=db_memory.id,
            project_id=db_memory.project_id,
            title=db_memory.title,
            content=db_memory.content,
            author_id=db_memory.author_id,
            content_type=db_memory.content_type,
            tags=db_memory.tags,
            entities=db_memory.entities,
            relationships=db_memory.relationships,
            version=db_memory.version,
            collaborators=db_memory.collaborators,
            is_public=db_memory.is_public,
            status=db_memory.status,
            processing_status=db_memory.processing_status,
            metadata=db_memory.meta,
            created_at=db_memory.created_at,
            updated_at=db_memory.updated_at,
        )

    def _to_db(self, domain_entity: Memory) -> DBMemory:
        """Convert domain entity to database model."""
        return DBMemory(
            id=domain_entity.id,
            project_id=domain_entity.project_id,
            title=domain_entity.title,
            content=domain_entity.content,
            content_type=domain_entity.content_type,
            tags=domain_entity.tags,
            entities=domain_entity.entities,
            relationships=domain_entity.relationships,
            version=domain_entity.version,
            author_id=domain_entity.author_id,
            collaborators=domain_entity.collaborators,
            is_public=domain_entity.is_public,
            status=domain_entity.status,
            processing_status=domain_entity.processing_status,
            meta=domain_entity.metadata,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )
