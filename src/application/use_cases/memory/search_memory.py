from dataclasses import dataclass
from typing import Any

from src.domain.ports.services.graph_service_port import GraphServicePort


@dataclass
class SearchMemoryQuery:
    """Query to search memories (read-only operation)."""

    query: str
    project_id: str | None = None
    limit: int = 10
    tenant_id: str | None = None
    user_id: str | None = None


# Backward compatibility alias
SearchMemoryCommand = SearchMemoryQuery


class SearchMemoryUseCase:
    def __init__(self, graph_service: GraphServicePort) -> None:
        self._graph_service = graph_service

    async def execute(self, command: SearchMemoryQuery) -> list[Any]:
        return await self._graph_service.search(
            query=command.query, project_id=command.project_id, limit=command.limit
        )
