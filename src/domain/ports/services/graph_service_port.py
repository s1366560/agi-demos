from abc import ABC, abstractmethod
from typing import Any

from src.domain.model.memory.episode import Episode


class GraphServicePort(ABC):
    @abstractmethod
    async def add_episode(self, episode: Episode) -> Episode:
        pass

    @abstractmethod
    async def search(
        self, query: str, project_id: str | None = None, limit: int = 10
    ) -> list[Any]:
        # Returns list of MemoryItems (defined in DTOs usually, or domain items)
        pass

    @abstractmethod
    async def get_graph_data(self, project_id: str, limit: int = 100) -> dict[str, Any]:
        pass

    @abstractmethod
    async def delete_episode(self, episode_name: str) -> bool:
        pass

    @abstractmethod
    async def delete_episode_by_memory_id(self, memory_id: str) -> bool:
        pass

    @abstractmethod
    async def remove_episode(self, episode_uuid: str) -> bool:
        """
        Remove an episode using graphiti-core's remove_episode method.
        This properly cleans up orphaned entities and edges in the graph.

        Args:
            episode_uuid: The UUID of the episode to remove

        Returns:
            True if removal was successful
        """
        pass
