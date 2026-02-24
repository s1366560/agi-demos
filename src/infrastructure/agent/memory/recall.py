"""Auto-recall preprocessor for agent memory.

Searches memory chunks and knowledge graph before the agent processes
a user message, injecting relevant context into the system prompt.
"""

from __future__ import annotations

import logging
from typing import Any

from src.infrastructure.memory.prompt_safety import (
    looks_like_prompt_injection,
    sanitize_for_context,
)

logger = logging.getLogger(__name__)

_MAX_CONTEXT_CHARS = 4000


class MemoryRecallPreprocessor:
    """Searches memory before agent processing and formats context.

    Combines results from chunk-based search (PostgreSQL) and
    knowledge graph search (Neo4j) for comprehensive recall.
    """

    def __init__(
        self,
        chunk_search: Any = None,
        graph_search: Any = None,
    ) -> None:
        self._chunk_search = chunk_search
        self._graph_search = graph_search
        # Tracking for event emission
        self.last_results: list[dict] = []
        self.last_search_ms: int = 0

    async def recall(
        self,
        query: str,
        project_id: str,
        max_results: int = 3,
    ) -> str | None:
        """Search memory and format results for system prompt injection.

        Args:
            query: User's message to use as search query.
            project_id: Scope to project.
            max_results: Maximum results per source.

        Returns:
            Formatted memory context string, or None if no results.
        """
        import time

        if not query or not query.strip():
            self.last_results = []
            self.last_search_ms = 0
            return None

        start = time.monotonic()
        all_results: list[dict] = []

        # Search chunk index (PostgreSQL)
        if self._chunk_search:
            try:
                chunk_results = await self._chunk_search.search(query, project_id, max_results)
                for r in chunk_results:
                    date_str = r.created_at.strftime("%Y-%m-%d") if r.created_at else ""
                    all_results.append(
                        {
                            "content": r.content,
                            "score": r.score,
                            "source": "memory_index",
                            "category": r.category,
                            "source_type": r.source_type or "chunk",
                            "source_id": r.source_id or "",
                            "date": date_str,
                        }
                    )
            except Exception as e:
                logger.warning(f"Chunk search failed during recall: {e}")

        # Search knowledge graph (Neo4j)
        if self._graph_search:
            try:
                graph_results = await self._graph_search.search(
                    query,
                    project_id=project_id,
                    limit=max_results,
                )
                for r in graph_results:
                    content = ""
                    if hasattr(r, "fact"):
                        content = r.fact
                    elif hasattr(r, "content"):
                        content = r.content
                    elif isinstance(r, dict):
                        content = r.get("fact", r.get("content", str(r)))
                    if content:
                        created = getattr(r, "created_at", None)
                        date_str = created.strftime("%Y-%m-%d") if created else ""
                        all_results.append(
                            {
                                "content": content,
                                "score": getattr(r, "score", 0.5),
                                "source": "knowledge_graph",
                                "category": "entity",
                                "source_type": "graph",
                                "source_id": getattr(r, "uuid", ""),
                                "date": date_str,
                            }
                        )
            except Exception as e:
                logger.warning(f"Graph search failed during recall: {e}")

        if not all_results:
            self.last_results = []
            self.last_search_ms = int((time.monotonic() - start) * 1000)
            return None

        # Filter prompt injections
        safe_results = [r for r in all_results if not looks_like_prompt_injection(r["content"])]

        if not safe_results:
            self.last_results = []
            self.last_search_ms = int((time.monotonic() - start) * 1000)
            return None

        # Sort by score and deduplicate
        safe_results.sort(key=lambda x: x["score"], reverse=True)
        seen_content: set[str] = set()
        unique_results: list[dict] = []
        for r in safe_results:
            content_key = r["content"].strip().lower()
            if content_key not in seen_content:
                seen_content.add(content_key)
                unique_results.append(r)

        # Track for event emission
        self.last_results = unique_results
        self.last_search_ms = int((time.monotonic() - start) * 1000)

        return self._format_context(unique_results)

    def _format_context(self, results: list[dict]) -> str:
        """Format memory results with citations for system prompt injection."""
        lines = ["<relevant_memories>"]
        total_chars = 0

        for r in results:
            content = sanitize_for_context(r["content"])
            if total_chars + len(content) > _MAX_CONTEXT_CHARS:
                break
            category = r.get("category", "other")
            source_type = r.get("source_type", "")
            source_id = r.get("source_id", "")
            date = r.get("date", "")
            # Citation format: [category | source_type:source_id | date]
            citation_parts = [category]
            if source_type:
                src = f"{source_type}:{source_id}" if source_id else source_type
                citation_parts.append(src)
            if date:
                citation_parts.append(date)
            citation = " | ".join(citation_parts)
            lines.append(f"- [{citation}] {content}")
            total_chars += len(content)

        lines.append("</relevant_memories>")

        if len(lines) <= 2:
            return None

        return "\n".join(lines)
