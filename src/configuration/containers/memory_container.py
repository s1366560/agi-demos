"""DI sub-container for memory domain."""


from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.memory_service import MemoryService
from src.application.services.search_service import SearchService
from src.application.use_cases.memory.create_memory import (
    CreateMemoryUseCase as MemCreateMemoryUseCase,
)
from src.application.use_cases.memory.delete_memory import (
    DeleteMemoryUseCase as MemDeleteMemoryUseCase,
)
from src.application.use_cases.memory.get_memory import (
    GetMemoryUseCase as MemGetMemoryUseCase,
)
from src.application.use_cases.memory.list_memories import ListMemoriesUseCase
from src.application.use_cases.memory.search_memory import SearchMemoryUseCase
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.domain.ports.services.graph_service_port import GraphServicePort
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlMemoryRepository,
)


class MemoryContainer:
    """Sub-container for memory-related services and use cases.

    Provides factory methods for memory repository, service,
    search service, and all memory use cases.
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        graph_service: GraphServicePort | None = None,
    ) -> None:
        self._db = db
        self._graph_service = graph_service

    def memory_repository(self) -> MemoryRepository:
        """Get MemoryRepository for memory persistence."""
        return SqlMemoryRepository(self._db)

    def memory_service(self) -> MemoryService:
        """Get MemoryService for memory operations."""
        if not self._graph_service:
            raise ValueError("graph_service is required for MemoryService")
        return MemoryService(
            memory_repo=self.memory_repository(),
            graph_service=self._graph_service,
        )

    def search_service(self) -> SearchService:
        """Get SearchService for memory search operations."""
        if not self._graph_service:
            raise ValueError("graph_service is required for SearchService")
        return SearchService(
            graph_service=self._graph_service,
            memory_repo=self.memory_repository(),
        )

    def create_memory_use_case(self) -> MemCreateMemoryUseCase:
        """Get CreateMemoryUseCase with dependencies injected."""
        if not self._graph_service:
            raise ValueError("graph_service is required for CreateMemoryUseCase")
        return MemCreateMemoryUseCase(self.memory_repository(), self._graph_service)

    def get_memory_use_case(self) -> MemGetMemoryUseCase:
        """Get GetMemoryUseCase with dependencies injected."""
        return MemGetMemoryUseCase(self.memory_repository())

    def list_memories_use_case(self) -> ListMemoriesUseCase:
        """Get ListMemoriesUseCase with dependencies injected."""
        return ListMemoriesUseCase(self.memory_repository())

    def delete_memory_use_case(self) -> MemDeleteMemoryUseCase:
        """Get DeleteMemoryUseCase with dependencies injected."""
        if not self._graph_service:
            raise ValueError("graph_service is required for DeleteMemoryUseCase")
        return MemDeleteMemoryUseCase(self.memory_repository(), self._graph_service)

    def search_memory_use_case(self) -> SearchMemoryUseCase:
        """Get SearchMemoryUseCase with dependencies injected."""
        if not self._graph_service:
            raise ValueError("graph_service is required for SearchMemoryUseCase")
        return SearchMemoryUseCase(self._graph_service)
