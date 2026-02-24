from dataclasses import dataclass

from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository


@dataclass
class GetMemoryQuery:
    """Query to get a memory by ID"""

    memory_id: str


class GetMemoryUseCase:
    """Use case to get a memory by ID"""

    def __init__(self, memory_repository: MemoryRepository) -> None:
        self._memory_repo = memory_repository

    async def execute(self, query: GetMemoryQuery) -> Memory | None:
        """
        Get a memory by ID.

        Args:
            query: GetMemoryQuery containing memory_id

        Returns:
            Memory object if found, None otherwise
        """
        return await self._memory_repo.find_by_id(query.memory_id)
