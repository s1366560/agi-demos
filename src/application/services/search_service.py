"""
SearchService: Unified search across memories, entities, and communities.

This service provides a high-level search interface that aggregates results
from the graph service and memory repository, with support for filtering and
pagination.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.domain.ports.services.graph_service_port import GraphServicePort

logger = logging.getLogger(__name__)


class GraphContext:
    """Container for graph context around an entity"""

    def __init__(
        self, entity_id: str, entity_name: str, neighbors: list[dict[str, Any]], depth: int
    ) -> None:
        self.entity_id = entity_id
        self.entity_name = entity_name
        self.neighbors = neighbors
        self.depth = depth


class SearchResult:
    """Individual search result with metadata"""

    def __init__(
        self,
        id: str,
        type: str,
        title: str,
        content: str,
        score: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.type = type  # "memory", "entity", "community"
        self.title = title
        self.content = content
        self.score = score
        self.metadata = metadata or {}


class SearchResults:
    """Container for search results with pagination"""

    def __init__(
        self,
        query: str,
        results: list[SearchResult],
        total: int,
        page: int = 1,
        page_size: int = 10,
    ) -> None:
        self.query = query
        self.results = results
        self.total = total
        self.page = page
        self.page_size = page_size
        self.total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0


class SearchService:
    """Service for unified search across all content types"""

    def __init__(self, graph_service: GraphServicePort, memory_repo: MemoryRepository) -> None:
        self._graph_service = graph_service
        self._memory_repo = memory_repo

    async def search(
        self,
        query: str,
        project_id: str,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> SearchResults:
        """
        Unified search across episodes, entities, and communities.

        Args:
            query: Search query string
            project_id: Project ID to search within
            filters: Optional filters including:
                - content_type: Filter by type (memory, entity, community)
                - date_from: Start date for filtering
                - date_to: End date for filtering
                - tags: Filter by tags
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            SearchResults with matching items
        """
        filters = filters or {}
        page = (offset // limit) + 1 if limit > 0 else 1

        try:
            # Perform graph search (includes episodes and entities)
            graph_results = await self._graph_service.search(
                query=query,
                project_id=project_id,
                limit=limit * 2,  # Fetch more for filtering
            )

            # Convert to SearchResult objects
            results = []
            for item in graph_results:
                result_type = item.get("type", "unknown")

                # Apply content type filter if specified
                if "content_type" in filters:
                    if filters["content_type"] == "memory" and result_type != "episode":
                        continue
                    if filters["content_type"] == "entity" and result_type != "entity":
                        continue

                if result_type == "episode":
                    results.append(
                        SearchResult(
                            id=item.get("uuid", ""),
                            type="memory",
                            title=item.get("name", "Memory"),
                            content=item.get("content", "")[:500],  # Truncate long content
                            score=item.get("score", 0.0),
                            metadata={"uuid": item.get("uuid")},
                        )
                    )
                elif result_type == "entity":
                    results.append(
                        SearchResult(
                            id=item.get("uuid", ""),
                            type="entity",
                            title=item.get("name", "Entity"),
                            content=item.get("summary", "")[:500],
                            score=item.get("score", 0.0),
                            metadata={"uuid": item.get("uuid")},
                        )
                    )

            # Apply pagination
            paginated_results = results[offset : offset + limit]

            return SearchResults(
                query=query,
                results=paginated_results,
                total=len(results),
                page=page,
                page_size=limit,
            )

        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            raise

    async def search_memories_by_tags(
        self, tags: list[str], project_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Search memories by tags.

        Args:
            tags: List of tags to search for
            project_id: Project ID
            limit: Maximum number of results

        Returns:
            List of memories with matching tags
        """
        try:
            # Get all memories in project
            memories = await self._memory_repo.list_by_project(project_id, limit=limit * 2)

            # Filter by tags (match any tag)
            filtered = []
            for memory in memories:
                if any(tag in memory.tags for tag in tags):
                    filtered.append(
                        {
                            "id": memory.id,
                            "title": memory.title,
                            "content": memory.content[:500],
                            "tags": memory.tags,
                            "created_at": memory.created_at.isoformat()
                            if memory.created_at
                            else None,
                        }
                    )

                    if len(filtered) >= limit:
                        break

            return filtered

        except Exception as e:
            logger.error(f"Tag search failed: {e}")
            raise

    async def search_by_date_range(
        self,
        project_id: str,
        date_from: datetime,
        date_to: datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Search memories by date range.

        Args:
            project_id: Project ID
            date_from: Start date
            date_to: End date (optional, defaults to now)
            limit: Maximum number of results

        Returns:
            List of memories within date range
        """
        if date_to is None:
            date_to = datetime.now(UTC)

        try:
            # Get all memories in project
            memories = await self._memory_repo.list_by_project(project_id, limit=limit * 10)

            # Filter by date range
            filtered = []
            for memory in memories:
                if memory.created_at and date_from <= memory.created_at <= date_to:
                    filtered.append(
                        {
                            "id": memory.id,
                            "title": memory.title,
                            "content": memory.content[:500],
                            "created_at": memory.created_at.isoformat(),
                        }
                    )

                    if len(filtered) >= limit:
                        break

            return filtered

        except Exception as e:
            logger.error(f"Date range search failed: {e}")
            raise

    async def get_graph_context(
        self, entity_id: str, project_id: str, depth: int = 2, limit: int = 50
    ) -> GraphContext:
        """
        Get graph context around an entity.

        Args:
            entity_id: Entity ID to get context for
            project_id: Project ID
            depth: How many hops to traverse (default: 2)
            limit: Maximum number of neighbors to return

        Returns:
            GraphContext with entity and its neighbors
        """
        try:
            # Get graph data for the project
            graph_data = await self._graph_service.get_graph_data(
                project_id=project_id, limit=limit * depth
            )

            # Find the entity
            entity = None
            neighbors = []

            for node in graph_data.get("nodes", []):
                if node.get("uuid") == entity_id or node.get("id") == entity_id:
                    entity = node
                    break

            if not entity:
                raise ValueError(f"Entity {entity_id} not found in project {project_id}")

            # Find connected neighbors
            entity_id_key = entity.get("id", entity.get("uuid"))

            for edge in graph_data.get("edges", []):
                if edge.get("source") == entity_id_key:
                    # Find neighbor node
                    for node in graph_data.get("nodes", []):
                        if node.get("id") == edge.get("target"):
                            neighbors.append(
                                {
                                    "id": node.get("id"),
                                    "label": node.get("label"),
                                    "type": node.get("type"),
                                    "relation": edge.get("label"),
                                    "summary": node.get("summary", ""),
                                }
                            )
                            break
                elif edge.get("target") == entity_id_key:
                    # Find source node
                    for node in graph_data.get("nodes", []):
                        if node.get("id") == edge.get("source"):
                            neighbors.append(
                                {
                                    "id": node.get("id"),
                                    "label": node.get("label"),
                                    "type": node.get("type"),
                                    "relation": edge.get("label"),
                                    "summary": node.get("summary", ""),
                                }
                            )
                            break

            return GraphContext(
                entity_id=entity_id,
                entity_name=entity.get("label", entity.get("name", "")),
                neighbors=neighbors[:limit],
                depth=depth,
            )

        except Exception as e:
            logger.error(f"Failed to get graph context for entity {entity_id}: {e}")
            raise

    async def get_recent_activity(
        self, project_id: str, days: int = 7, limit: int = 20
    ) -> dict[str, Any]:
        """
        Get recent activity in a project.

        Args:
            project_id: Project ID
            days: Number of days to look back
            limit: Maximum number of items

        Returns:
            Dictionary with recent memories, entities, and activity summary
        """
        try:
            date_from = datetime.now(UTC) - timedelta(days=days)

            # Get recent memories
            memories = await self.search_by_date_range(
                project_id=project_id, date_from=date_from, limit=limit
            )

            # Get graph data for entity activity
            graph_data = await self._graph_service.get_graph_data(
                project_id=project_id, limit=limit
            )

            entity_count = len(
                [n for n in graph_data.get("nodes", []) if n.get("type") == "entity"]
            )

            return {
                "project_id": project_id,
                "days": days,
                "recent_memories": memories,
                "memory_count": len(memories),
                "entity_count": entity_count,
                "total_nodes": len(graph_data.get("nodes", [])),
                "total_edges": len(graph_data.get("edges", [])),
            }

        except Exception as e:
            logger.error(f"Failed to get recent activity for project {project_id}: {e}")
            raise
