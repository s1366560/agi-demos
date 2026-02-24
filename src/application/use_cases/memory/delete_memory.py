from typing import Optional

from pydantic import BaseModel, field_validator

from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.domain.ports.services.graph_service_port import GraphServicePort


class DeleteMemoryCommand(BaseModel):
    """Command to delete a memory"""

    model_config = {"frozen": True}

    memory_id: str
    project_id: Optional[str] = None  # For validation if needed

    @field_validator("memory_id")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v


class DeleteMemoryUseCase:
    def __init__(self, memory_repository: MemoryRepository, graph_service: GraphServicePort):
        self._memory_repo = memory_repository
        self._graph_service = graph_service

    async def execute(self, command: DeleteMemoryCommand) -> None:
        # 1. Check if memory exists
        memory = await self._memory_repo.find_by_id(command.memory_id)
        if not memory:
            # Idempotent: if not found, consider deleted
            return

        # 2. Delete from Graphiti (nodes/edges)
        try:
            await self._graph_service.delete_episode_by_memory_id(command.memory_id)
        except Exception as e:
            # Log but continue to ensure DB consistency
            print(f"Failed to delete from Graphiti: {e}")

        # 3. Delete from DB
        await self._memory_repo.delete(command.memory_id)
