"""
MemoryService: Business logic for memory management with graph integration.

This service handles memory CRUD operations, integrates with the graph service
for entity extraction and knowledge graph operations.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.domain.model.enums import ProcessingStatus
from src.domain.model.memory.episode import Episode, SourceType
from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.domain.ports.services.graph_service_port import GraphServicePort

logger = logging.getLogger(__name__)


class SearchResults:
    """Container for search results with metadata"""

    def __init__(
        self, memories: List[Dict[str, Any]], entities: List[Dict[str, Any]], total: int, query: str
    ):
        self.memories = memories
        self.entities = entities
        self.total = total
        self.query = query


class MemoryService:
    """Service for managing memories with graph integration"""

    def __init__(self, memory_repo: MemoryRepository, graph_service: GraphServicePort):
        self._memory_repo = memory_repo
        self._graph_service = graph_service

    async def create_memory(
        self,
        title: str,
        content: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        content_type: str = "text",
        tags: Optional[List[str]] = None,
        is_public: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Memory:
        """
        Create a new memory and queue it for background processing.

        This method:
        1. Creates the memory in the database
        2. Creates an episode and adds it to the graph
        3. Queues background processing for entity extraction

        Args:
            title: Memory title
            content: Memory content
            project_id: Project ID to associate with
            user_id: User ID creating the memory
            tenant_id: Tenant ID for multi-tenancy
            content_type: Type of content (text, json, etc.)
            tags: Optional list of tags
            is_public: Whether memory is publicly visible
            metadata: Optional metadata dictionary

        Returns:
            Created memory with processing_status=PENDING
        """
        # Create memory entity
        memory = Memory(
            id=Memory.generate_id(),
            project_id=project_id,
            title=title,
            content=content,
            author_id=user_id,
            content_type=content_type,
            tags=tags or [],
            is_public=is_public,
            status="ENABLED",
            processing_status=ProcessingStatus.PENDING.value,
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc),
        )

        # Save memory to database
        await self._memory_repo.save(memory)
        logger.info(f"Saved memory {memory.id} to database")

        # Create episode for graph processing
        episode = Episode(
            id=Episode.generate_id(),
            name=title,
            content=content,
            source_type=SourceType.TEXT,
            valid_at=datetime.now(timezone.utc),
            metadata={
                "memory_id": memory.id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "user_id": user_id,
            },
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            status=ProcessingStatus.PENDING.value,
        )

        # Add episode to graph (this also queues background processing)
        try:
            await self._graph_service.add_episode(episode)
            logger.info(f"Added episode {episode.id} to graph for memory {memory.id}")
        except Exception as e:
            logger.error(f"Failed to add episode to graph: {e}")
            # Update memory status to failed
            memory.processing_status = ProcessingStatus.FAILED.value
            await self._memory_repo.save(memory)
            raise

        return memory

    async def get_memory(self, memory_id: str) -> Optional[Memory]:
        """
        Retrieve a memory by ID.

        Args:
            memory_id: Memory ID

        Returns:
            Memory if found, None otherwise
        """
        return await self._memory_repo.find_by_id(memory_id)

    async def list_memories(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> List[Memory]:
        """
        List memories in a project.

        Args:
            project_id: Project ID
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of memories
        """
        return await self._memory_repo.list_by_project(project_id, limit=limit, offset=offset)

    async def search_memories(self, query: str, project_id: str, limit: int = 10) -> SearchResults:
        """
        Search for memories using semantic search.

        Args:
            query: Search query
            project_id: Project ID to search within
            limit: Maximum number of results

        Returns:
            SearchResults containing memories and entities
        """
        try:
            # Use graph service for semantic search
            results = await self._graph_service.search(
                query=query, project_id=project_id, limit=limit
            )

            # Separate results into memories and entities
            memories = []
            entities = []

            for item in results:
                if item.get("type") == "episode":
                    # Convert episode result to memory format
                    memories.append(
                        {
                            "type": "memory",
                            "content": item.get("content", ""),
                            "uuid": item.get("uuid", ""),
                            "score": item.get("score", 0.0),
                        }
                    )
                elif item.get("type") == "entity":
                    entities.append(
                        {
                            "type": "entity",
                            "name": item.get("name", ""),
                            "summary": item.get("summary", ""),
                            "uuid": item.get("uuid", ""),
                            "score": item.get("score", 0.0),
                        }
                    )

            return SearchResults(
                memories=memories,
                entities=entities,
                total=len(memories) + len(entities),
                query=query,
            )

        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            raise

    async def update_memory(
        self,
        memory_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        is_public: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Memory:
        """
        Update memory properties.

        If content is updated, the memory will be reprocessed.

        Args:
            memory_id: Memory ID
            title: New title (optional)
            content: New content (optional)
            tags: New tags (optional)
            is_public: New public status (optional)
            metadata: New metadata (optional)

        Returns:
            Updated memory

        Raises:
            ValueError: If memory doesn't exist
        """
        memory = await self._memory_repo.find_by_id(memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")

        # Track if content changed for reprocessing
        content_changed = False

        # Update fields if provided
        if title is not None:
            memory.title = title
        if content is not None:
            if content != memory.content:
                content_changed = True
            memory.content = content
        if tags is not None:
            memory.tags = tags
        if is_public is not None:
            memory.is_public = is_public
        if metadata is not None:
            memory.metadata.update(metadata)

        memory.updated_at = datetime.now(timezone.utc)

        # If content changed, reprocess by updating processing status
        if content_changed:
            memory.processing_status = ProcessingStatus.PENDING.value

        await self._memory_repo.save(memory)
        logger.info(f"Updated memory {memory_id}")

        # If content changed, create new episode for reprocessing
        if content_changed:
            try:
                episode = Episode(
                    id=Episode.generate_id(),
                    name=memory.title,
                    content=memory.content,
                    source_type=SourceType.TEXT,
                    valid_at=datetime.now(timezone.utc),
                    metadata={
                        "memory_id": memory.id,
                        "tenant_id": memory.metadata.get("tenant_id"),
                        "project_id": memory.project_id,
                        "user_id": memory.author_id,
                        "reprocess": True,
                    },
                    tenant_id=memory.metadata.get("tenant_id"),
                    project_id=memory.project_id,
                    user_id=memory.author_id,
                    status=ProcessingStatus.PENDING.value,
                )
                await self._graph_service.add_episode(episode)
                logger.info(f"Queued reprocessing for memory {memory_id}")
            except Exception as e:
                logger.error(f"Failed to queue reprocessing: {e}")
                memory.processing_status = ProcessingStatus.FAILED.value
                await self._memory_repo.save(memory)
                raise

        return memory

    async def delete_memory(self, memory_id: str) -> None:
        """
        Delete a memory and its associated episode from the graph.

        Uses graphiti-core's remove_episode method which properly cleans up:
        - Edges created by this episode
        - Orphaned entity nodes (only referenced by this episode)

        Args:
            memory_id: Memory ID

        Raises:
            ValueError: If memory doesn't exist
        """
        memory = await self._memory_repo.find_by_id(memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")

        # Delete episode from graph using the proper remove_episode method
        # This ensures orphaned entities and edges are cleaned up
        graph_cleanup_failed = False
        try:
            await self._graph_service.remove_episode(memory_id)
            logger.info(f"Removed episode from graph with proper cleanup for memory {memory_id}")
        except Exception as e:
            graph_cleanup_failed = True
            logger.warning(
                f"Failed to remove episode from graph for memory {memory_id}: {e}. "
                "Orphaned data may remain in Neo4j. Continuing with database deletion."
            )

        # Delete memory from database
        await self._memory_repo.delete(memory_id)

        if graph_cleanup_failed:
            logger.warning(f"Deleted memory {memory_id} from database but graph cleanup failed")
        else:
            logger.info(f"Deleted memory {memory_id}")

    async def share_memory(self, memory_id: str, collaborators: List[str]) -> Memory:
        """
        Share a memory with specific collaborators.

        Args:
            memory_id: Memory ID
            collaborators: List of user IDs to share with

        Returns:
            Updated memory

        Raises:
            ValueError: If memory doesn't exist
        """
        memory = await self._memory_repo.find_by_id(memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")

        # Add collaborators (avoid duplicates)
        for user_id in collaborators:
            if user_id not in memory.collaborators:
                memory.collaborators.append(user_id)

        memory.updated_at = datetime.now(timezone.utc)
        await self._memory_repo.save(memory)
        logger.info(f"Shared memory {memory_id} with {len(collaborators)} collaborators")

        return memory

    async def get_processing_status(self, memory_id: str) -> str:
        """
        Get the processing status of a memory.

        Args:
            memory_id: Memory ID

        Returns:
            Processing status string

        Raises:
            ValueError: If memory doesn't exist
        """
        memory = await self._memory_repo.find_by_id(memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")

        return memory.processing_status
