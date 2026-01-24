from abc import ABC, abstractmethod


class QueuePort(ABC):
    @abstractmethod
    async def add_episode(
        self,
        group_id: str,
        name: str,
        content: str,
        source_description: str,
        episode_type: str,
        uuid: str,
        tenant_id: str = None,
        project_id: str = None,
        user_id: str = None,
        memory_id: str = None,
    ) -> None:
        pass
