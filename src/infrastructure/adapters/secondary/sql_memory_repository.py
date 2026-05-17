from typing import override

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Memory as MemoryModel


class SqlAlchemyMemoryRepository(MemoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_domain(self, model: MemoryModel) -> Memory:
        return Memory(
            id=model.id,
            project_id=model.project_id,
            title=model.title,
            content=model.content,
            author_id=model.author_id,
            content_type=model.content_type,
            tags=model.tags,
            entities=model.entities,
            relationships=model.relationships,
            collaborators=model.collaborators,
            is_public=model.is_public,
            status=model.status,
            processing_status=model.processing_status,
            metadata=model.meta,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_model(self, entity: Memory) -> MemoryModel:
        return MemoryModel(
            id=entity.id,
            project_id=entity.project_id,
            title=entity.title,
            content=entity.content,
            author_id=entity.author_id,
            content_type=entity.content_type,
            tags=entity.tags,
            entities=entity.entities,
            relationships=entity.relationships,
            collaborators=entity.collaborators,
            is_public=entity.is_public,
            status=entity.status,
            processing_status=entity.processing_status,
            meta=entity.metadata,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    async def save(self, memory: Memory) -> Memory:
        model = self._to_model(memory)
        # Check if exists to merge or add
        # Simple merge for now
        await self._session.merge(model)
        await self._session.commit()
        return memory

    async def find_by_id(self, memory_id: str) -> Memory | None:
        result = await self._session.execute(
            refresh_select_statement(select(MemoryModel).where(MemoryModel.id == memory_id))
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def list_by_project(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        result = await self._session.execute(
            refresh_select_statement(
                select(MemoryModel)
                .where(MemoryModel.project_id == project_id)
                .limit(limit)
                .offset(offset)
            )
        )
        models = result.scalars().all()
        return [self._to_domain(m) for m in models]

    @override
    async def search_by_project(
        self, project_id: str, search: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        pattern = f"%{search}%"
        result = await self._session.execute(
            refresh_select_statement(
                select(MemoryModel)
                .where(MemoryModel.project_id == project_id)
                .where(or_(MemoryModel.title.ilike(pattern), MemoryModel.content.ilike(pattern)))
                .limit(limit)
                .offset(offset)
            )
        )
        models = result.scalars().all()
        return [self._to_domain(m) for m in models]

    async def delete(self, memory_id: str) -> bool:
        await self._session.execute(
            refresh_select_statement(delete(MemoryModel).where(MemoryModel.id == memory_id))
        )
        await self._session.commit()
        return True
