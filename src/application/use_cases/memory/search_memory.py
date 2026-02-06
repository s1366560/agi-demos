from dataclasses import dataclass
from typing import Any, List, Optional

from src.domain.ports.services.graph_service_port import GraphServicePort


@dataclass
class SearchMemoryQuery:
    """Query to search memories (read-only operation)."""

    query: str
    project_id: Optional[str] = None
    limit: int = 10
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None


# Backward compatibility alias
SearchMemoryCommand = SearchMemoryQuery


class SearchMemoryUseCase:
    def __init__(self, graph_service: GraphServicePort):
        self._graph_service = graph_service

    async def execute(self, command: SearchMemoryQuery) -> List[Any]:
        return await self._graph_service.search(
            query=command.query, project_id=command.project_id, limit=command.limit
        )
