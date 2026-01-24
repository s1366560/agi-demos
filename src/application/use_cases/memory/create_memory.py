from dataclasses import dataclass
from typing import Any, Dict, List

from src.domain.model.memory.episode import Episode, SourceType
from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.domain.ports.services.graph_service_port import GraphServicePort


@dataclass
class CreateMemoryCommand:
    project_id: str
    title: str
    content: str
    author_id: str
    tenant_id: str
    content_type: str = "text"
    tags: List[str] = None
    entities: List[Dict[str, Any]] = None
    relationships: List[Dict[str, Any]] = None
    collaborators: List[str] = None
    is_public: bool = False
    metadata: Dict[str, Any] = None


class CreateMemoryUseCase:
    def __init__(self, memory_repository: MemoryRepository, graph_service: GraphServicePort):
        self._memory_repo = memory_repository
        self._graph_service = graph_service

    async def execute(self, command: CreateMemoryCommand) -> Memory:
        # Create Memory Entity
        memory = Memory(
            project_id=command.project_id,
            title=command.title,
            content=command.content,
            author_id=command.author_id,
            content_type=command.content_type,
            tags=command.tags or [],
            entities=command.entities or [],
            relationships=command.relationships or [],
            collaborators=command.collaborators or [],
            is_public=command.is_public,
            metadata=command.metadata or {},
        )

        # Save to primary repository (DB)
        await self._memory_repo.save(memory)

        # Sync to Graph (Graphiti)
        if command.content_type == "text":
            try:
                episode = Episode(
                    name=command.title,
                    content=command.content,
                    source_type=SourceType.TEXT,
                    valid_at=memory.created_at,
                    tenant_id=command.tenant_id,
                    project_id=command.project_id,
                    user_id=command.author_id,
                    metadata={
                        "memory_id": memory.id,
                        "project_id": command.project_id,
                        "tenant_id": command.tenant_id,
                        "entities": command.entities,
                        "relationships": command.relationships,
                    },
                )
                await self._graph_service.add_episode(episode)
            except Exception as e:
                # Log error but don't fail the operation (consistent with current behavior)
                # In a real system, we might want to use an Outbox pattern or event bus
                print(f"Failed to sync to Graphiti: {e}")

        return memory
