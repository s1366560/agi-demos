from abc import ABC, abstractmethod

from src.domain.model.memory.memory import Memory


class MemoryRepository(ABC):
    @abstractmethod
    async def save(self, memory: Memory) -> None:
        pass

    @abstractmethod
    async def find_by_id(self, memory_id: str) -> Memory | None:
        pass

    @abstractmethod
    async def list_by_project(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        pass

    @abstractmethod
    async def delete(self, memory_id: str) -> None:
        pass
