"""Memory accessor for SubAgent execution.

Provides SubAgents with read/write access to the project's knowledge graph.
Default mode is read-only; write access must be explicitly granted.

Usage:
    accessor = MemoryAccessor(graph_service, project_id="proj-1")
    results = await accessor.search("user preferences")
    context_snippet = accessor.format_for_context(results)
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Limits to prevent SubAgents from overwhelming the context window
DEFAULT_MAX_RESULTS = 5
DEFAULT_MAX_CHARS = 3000


class GraphSearchable(Protocol):
    """Minimal protocol for graph search (avoids tight coupling to GraphServicePort)."""

    async def search(
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[Any]: ...


class GraphWritable(Protocol):
    """Protocol for graph write operations."""

    async def add_episode(self, episode: Any) -> Any: ...


@dataclass(frozen=True)
class MemoryItem:
    """A single memory item retrieved from the knowledge graph.

    Attributes:
        content: The text content (episode content or entity summary).
        item_type: "episode" or "entity".
        score: Relevance score from search.
        source_id: UUID of the source node.
        metadata: Additional metadata from the graph.
    """

    content: str
    item_type: str = "episode"
    score: float = 0.0
    source_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryWriteResult:
    """Result of writing memory back to the knowledge graph.

    Attributes:
        success: Whether the write succeeded.
        episode_id: ID of the created episode (if successful).
        error: Error message on failure.
    """

    success: bool
    episode_id: str = ""
    error: str | None = None


class MemoryAccessor:
    """Provides SubAgents with scoped access to the knowledge graph.

    Features:
    - Read: hybrid search over memories/entities
    - Write: persist SubAgent findings as new episodes (opt-in)
    - Formatting: convert results to context-friendly text
    - Isolation: always scoped to a project_id

    Args:
        graph_service: Graph service implementing search protocol.
        project_id: Project scope for all operations.
        writable: Whether write operations are allowed (default False).
        max_results: Maximum search results to return.
        max_chars: Maximum characters for formatted context.
    """

    def __init__(
        self,
        graph_service: Any,
        project_id: str,
        writable: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self._graph = graph_service
        self._project_id = project_id
        self._writable = writable
        self._max_results = max_results
        self._max_chars = max_chars

    @property
    def is_writable(self) -> bool:
        return self._writable

    async def search(self, query: str, limit: int | None = None) -> list[MemoryItem]:
        """Search the knowledge graph for relevant memories.

        Args:
            query: Natural language search query.
            limit: Max results (defaults to configured max_results).

        Returns:
            List of MemoryItem sorted by relevance.
        """
        effective_limit = limit or self._max_results

        try:
            raw_results = await self._graph.search(
                query=query,
                project_id=self._project_id,
                limit=effective_limit,
            )
            return self._normalize_results(raw_results)
        except Exception as e:
            logger.warning(f"[MemoryAccessor] Search failed: {e}")
            return []

    async def write(
        self,
        content: str,
        source_description: str = "subagent",
    ) -> MemoryWriteResult:
        """Write content as a new episode to the knowledge graph.

        Requires writable=True at construction time.

        Args:
            content: Text content to persist.
            source_description: Description of the source (SubAgent name).

        Returns:
            MemoryWriteResult with success status.
        """
        if not self._writable:
            return MemoryWriteResult(
                success=False,
                error="Write access not granted for this SubAgent",
            )

        try:
            from src.domain.model.memory.episode import Episode, SourceType

            episode = Episode(
                content=content,
                source_type=SourceType.CONVERSATION,
                valid_at=datetime.now(UTC),
                project_id=self._project_id,
                name=f"subagent:{source_description}",
                metadata={"source": "subagent", "subagent": source_description},
            )

            saved = await self._graph.add_episode(episode)
            episode_id = getattr(saved, "uuid", getattr(saved, "id", ""))

            logger.info(f"[MemoryAccessor] Wrote episode {episode_id} from {source_description}")
            return MemoryWriteResult(success=True, episode_id=str(episode_id))

        except Exception as e:
            logger.warning(f"[MemoryAccessor] Write failed: {e}")
            return MemoryWriteResult(success=False, error=str(e))

    def format_for_context(self, items: list[MemoryItem]) -> str:
        """Format memory items as a text snippet for SubAgent context injection.

        Args:
            items: List of MemoryItem from search.

        Returns:
            Formatted string suitable for system/user message injection.
        """
        if not items:
            return ""

        parts: list[str] = ["[Relevant memories from knowledge graph]"]
        total_chars = 0

        for i, item in enumerate(items, 1):
            entry = f"{i}. [{item.item_type}] {item.content}"

            if total_chars + len(entry) > self._max_chars:
                remaining = self._max_chars - total_chars
                if remaining > 50:
                    parts.append(entry[:remaining] + "...")
                break

            parts.append(entry)
            total_chars += len(entry)

        return "\n".join(parts)

    def _normalize_results(self, raw_results: Any) -> list[MemoryItem]:
        """Normalize raw graph search results to MemoryItem list.

        Handles both list-of-dicts and SearchResultItem-like objects.
        """
        if not raw_results:
            return []

        items: list[MemoryItem] = []

        for r in raw_results:
            if isinstance(r, dict):
                items.append(
                    MemoryItem(
                        content=r.get("content", r.get("summary", "")),
                        item_type=r.get("type", "episode"),
                        score=float(r.get("score", 0.0)),
                        source_id=r.get("uuid", r.get("id", "")),
                        metadata=r.get("metadata", {}),
                    )
                )
            elif hasattr(r, "content"):
                items.append(
                    MemoryItem(
                        content=getattr(r, "content", "") or getattr(r, "summary", ""),
                        item_type=getattr(r, "type", "episode"),
                        score=float(getattr(r, "score", 0.0)),
                        source_id=getattr(r, "uuid", getattr(r, "id", "")),
                        metadata=getattr(r, "metadata", {}),
                    )
                )

        return items
