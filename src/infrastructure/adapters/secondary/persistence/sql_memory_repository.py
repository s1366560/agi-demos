"""
SQLAlchemy implementation of MemoryRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.infrastructure.adapters.secondary.persistence.models import Memory as DBMemory

logger = logging.getLogger(__name__)


class SqlAlchemyMemoryRepository(MemoryRepository):
    """SQLAlchemy implementation of MemoryRepository"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, memory: Memory) -> None:
        """Save a memory (create or update)"""
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
            db_memory.updated_at = memory.updated_at
        else:
            # Create new memory
            db_memory = DBMemory(
                id=memory.id,
                project_id=memory.project_id,
                title=memory.title,
                content=memory.content,
                content_type=memory.content_type,
                tags=memory.tags,
                entities=memory.entities,
                relationships=memory.relationships,
                version=memory.version,
                author_id=memory.author_id,
                collaborators=memory.collaborators,
                is_public=memory.is_public,
                status=memory.status,
                processing_status=memory.processing_status,
                meta=memory.metadata,
                created_at=memory.created_at,
                updated_at=memory.updated_at,
            )
            self._session.add(db_memory)

        await self._session.flush()

    async def find_by_id(self, memory_id: str) -> Optional[Memory]:
        """Find a memory by ID"""
        result = await self._session.execute(select(DBMemory).where(DBMemory.id == memory_id))
        db_memory = result.scalar_one_or_none()
        return self._to_domain(db_memory) if db_memory else None

    async def list_by_project(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> List[Memory]:
        """List all memories for a project"""
        result = await self._session.execute(
            select(DBMemory).where(DBMemory.project_id == project_id).offset(offset).limit(limit)
        )
        db_memories = result.scalars().all()
        return [self._to_domain(m) for m in db_memories]

    async def delete(self, memory_id: str) -> None:
        """Delete a memory"""
        result = await self._session.execute(select(DBMemory).where(DBMemory.id == memory_id))
        db_memory = result.scalar_one_or_none()
        if db_memory:
            await self._session.delete(db_memory)
            await self._session.flush()

    def _to_domain(self, db_memory: DBMemory) -> Memory:
        """Convert database model to domain model"""
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
