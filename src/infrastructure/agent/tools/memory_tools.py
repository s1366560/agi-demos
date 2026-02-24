"""Memory search and retrieval tools for the ReAct agent.

Provides the agent with active memory capabilities:
- memory_search: Semantic + keyword hybrid search across memory chunks
- memory_get: Retrieve full content of a specific memory chunk

These tools let the agent proactively search for relevant context
rather than relying solely on automatic recall.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class MemorySearchTool(AgentTool):
    """Search the project's memory store using hybrid retrieval.

    Combines vector similarity and full-text search to find
    relevant memories, facts, preferences, and past decisions.
    """

    def __init__(
        self,
        chunk_search: Any,
        graph_service: Any = None,
        project_id: str = "",
    ):
        super().__init__(
            name="memory_search",
            description=(
                "Search the project memory for relevant context. Use this BEFORE answering "
                "questions about prior work, decisions, user preferences, past conversations, "
                "or any information that may have been stored previously. "
                "Returns ranked results with source citations."
            ),
        )
        self._chunk_search = chunk_search
        self._graph_service = graph_service
        self._project_id = project_id

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query describing what you want to find in memory.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5).",
                    "default": 5,
                },
                "category": {
                    "type": "string",
                    "description": "Optional filter by category: preference, fact, decision, entity.",
                    "enum": ["preference", "fact", "decision", "entity"],
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:  # noqa: ANN401
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 5)
        category = kwargs.get("category")

        if not query:
            return json.dumps({"error": "query parameter is required"})

        results = []

        # Search memory chunks via hybrid search
        try:
            chunk_results = await self._chunk_search.search(
                query=query,
                project_id=self._project_id,
                limit=max_results,
            )
            for r in chunk_results:
                # ChunkSearchResult is a dataclass - use attribute access
                item = {
                    "content": r.content,
                    "score": round(r.score, 3),
                    "category": r.category or "other",
                    "source_type": r.source_type or "unknown",
                    "source_id": r.source_id or "",
                    "created_at": str(r.created_at) if r.created_at else "",
                }
                if category and item["category"] != category:
                    continue
                results.append(item)
        except Exception as e:
            logger.warning(f"Memory chunk search failed: {e}")

        # Also search knowledge graph if available
        if self._graph_service and len(results) < max_results:
            try:
                graph_results = await self._graph_service.search(query, project_id=self._project_id)
                for gr in graph_results[: max_results - len(results)]:
                    # Graph results may be objects or dicts
                    if isinstance(gr, dict):
                        content = gr.get("content", "") or gr.get("fact", "")
                        score = gr.get("score", 0.5)
                        uid = gr.get("uuid", "")
                        created = gr.get("created_at", "")
                    else:
                        content = getattr(gr, "fact", "") or getattr(gr, "content", "")
                        score = getattr(gr, "score", 0.5)
                        uid = getattr(gr, "uuid", "")
                        created = getattr(gr, "created_at", "")
                    if content:
                        results.append(
                            {
                                "content": content,
                                "score": round(float(score), 3),
                                "category": "fact",
                                "source_type": "knowledge_graph",
                                "source_id": str(uid),
                                "created_at": str(created) if created else "",
                            }
                        )
            except Exception as e:
                logger.debug(f"Graph search failed (non-critical): {e}")

        # Format citations
        for i, r in enumerate(results):
            created = r.get("created_at", "")
            if isinstance(created, datetime):
                created = created.strftime("%Y-%m-%d")
            elif isinstance(created, str) and "T" in created:
                created = created.split("T")[0]
            r["citation"] = (
                f"[{r['category']} | {r['source_type']}:{r['source_id'][:8]} | {created}]"
            )

        return json.dumps(
            {
                "results": results[:max_results],
                "total": len(results),
                "query": query,
            },
            ensure_ascii=False,
            default=str,
        )


class MemoryGetTool(AgentTool):
    """Retrieve the full content of a specific memory chunk by ID."""

    def __init__(
        self,
        session_factory: Optional[Callable] = None,
        project_id: str = "",
    ):
        super().__init__(
            name="memory_get",
            description=(
                "Retrieve the full content of a specific memory entry by its source_id. "
                "Use after memory_search to get complete details of a result."
            ),
        )
        self._session_factory = session_factory
        self._project_id = project_id

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "The source_id from a memory_search result.",
                },
            },
            "required": ["source_id"],
        }

    async def execute(self, **kwargs: Any) -> str:  # noqa: ANN401
        source_id = kwargs.get("source_id", "")
        if not source_id:
            return json.dumps({"error": "source_id parameter is required"})

        if not self._session_factory:
            return json.dumps({"error": "Memory storage not available"})

        try:
            session = self._session_factory()
            try:
                from sqlalchemy import select

                from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk

                query = (
                    select(MemoryChunk)
                    .where(
                        MemoryChunk.source_id == source_id,
                        MemoryChunk.project_id == self._project_id,
                    )
                    .order_by(MemoryChunk.chunk_index)
                )
                result = await session.execute(query)
                chunks = list(result.scalars().all())

                if not chunks:
                    return json.dumps({"error": f"No memory found for source_id: {source_id}"})

                items = []
                for chunk in chunks:
                    items.append(
                        {
                            "content": chunk.content,
                            "category": chunk.category or "other",
                            "chunk_index": chunk.chunk_index,
                            "created_at": str(chunk.created_at) if chunk.created_at else "",
                        }
                    )

                return json.dumps(
                    {"source_id": source_id, "chunks": items, "total": len(items)},
                    ensure_ascii=False,
                    default=str,
                )
            finally:
                await session.close()
        except Exception as e:
            logger.warning(f"Memory get failed: {e}")
            return json.dumps({"error": f"Failed to retrieve memory: {e}"})
