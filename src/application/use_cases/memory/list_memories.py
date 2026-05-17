from dataclasses import dataclass

from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository


@dataclass
class ListMemoriesQuery:
    """Query to list memories"""

    project_id: str
    limit: int = 50
    offset: int = 0
    search: str | None = None


class ListMemoriesUseCase:
    """Use case to list memories for a project"""

    def __init__(self, memory_repository: MemoryRepository) -> None:
        self._memory_repo = memory_repository

    async def execute(self, query: ListMemoriesQuery) -> list[Memory]:
        """
        List memories for a project.

        Args:
            query: ListMemoriesQuery containing filters and pagination

        Returns:
            List of Memory objects
        """
        if query.search and query.search.strip():
            return await self._memory_repo.search_by_project(
                project_id=query.project_id,
                search=query.search.strip(),
                limit=query.limit,
                offset=query.offset,
            )

        return await self._memory_repo.list_by_project(
            project_id=query.project_id, limit=query.limit, offset=query.offset
        )
