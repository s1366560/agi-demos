from abc import ABC, abstractmethod

from src.domain.model.memory.memory import Memory
from src.domain.model.memory.processing import MemoryProcessingSource


class MemoryRepository(ABC):
    async def update_processing_status(self, source: MemoryProcessingSource, status: str) -> bool:
        """Update derived state atomically, never fall back to a full object save."""
        raise NotImplementedError("Conditional memory processing updates are not supported")

    @abstractmethod
    async def save(self, memory: Memory) -> Memory:
        pass

    @abstractmethod
    async def find_by_id(self, memory_id: str) -> Memory | None:
        pass

    @abstractmethod
    async def list_by_project(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        pass

    async def search_by_project(
        self, project_id: str, search: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        """Search memories within a project.

        Concrete repositories should override this when they can push search
        into storage. The fallback keeps older in-memory or test repositories
        compatible while preserving the public use-case behavior.
        """
        needle = search.casefold()
        memories = await self.list_by_project(project_id=project_id, limit=limit, offset=offset)
        return [
            memory
            for memory in memories
            if needle in memory.title.casefold() or needle in memory.content.casefold()
        ]

    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        pass
