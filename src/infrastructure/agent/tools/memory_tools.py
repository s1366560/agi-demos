"""Memory tools for the ReAct agent.

Provides the agent with full memory CRUD capabilities:
- memory_search: Semantic + keyword hybrid search across memory chunks
- memory_get: Retrieve full content of a specific memory chunk
- memory_create: Create a new memory entry in the project knowledge base
- memory_update: Update an existing memory entry (title, content, tags, metadata)
- memory_delete: Permanently delete a memory entry and clean up graph data

These tools let the agent proactively manage the project knowledge base
rather than relying solely on automatic recall.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid as uuid_mod
from collections.abc import Callable
from datetime import datetime
from typing import Any, override

from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

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
    ) -> None:
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

    @override
    def get_parameters_schema(self) -> dict[str, Any]:
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

    @override
    async def execute(self, **kwargs: Any) -> str:
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
                category=category,
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
                results.append(item)
        except Exception as e:
            logger.warning(f"Memory chunk search failed: {e}")

        # Also search knowledge graph if available
        if self._graph_service and len(results) < max_results:
            await self._search_graph(results, query, max_results)

        # Format citations
        for _i, r in enumerate(results):
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

    async def _search_graph(
        self, results: list[dict[str, Any]], query: str, max_results: int
    ) -> None:
        """Search knowledge graph and append results in-place."""
        try:
            graph_results = await self._graph_service.search(query, project_id=self._project_id)
            for gr in graph_results[: max_results - len(results)]:
                content, score, uid, created = self._extract_graph_fields(gr)
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

    @staticmethod
    def _extract_graph_fields(gr: Any) -> tuple[str, float, str, str]:
        """Extract content, score, source_id, created_at from a graph result.

        Prefers memory_id over uuid for source_id so that memory_get can
        find the corresponding MemoryChunk (which uses memory.id as source_id).
        """
        if isinstance(gr, dict):
            content = gr.get("content", "") or gr.get("fact", "")
            score = gr.get("score", 0.5)
            uid = gr.get("memory_id", "") or gr.get("uuid", "")
            created = gr.get("created_at", "")
        else:
            content = getattr(gr, "fact", "") or getattr(gr, "content", "")
            score = getattr(gr, "score", 0.5)
            uid = getattr(gr, "memory_id", "") or getattr(gr, "uuid", "")
            created = getattr(gr, "created_at", "")
        return content, score, uid, created


async def _execute_memory_get(
    session_factory: Callable[..., Any],
    project_id: str,
    source_id: str,
) -> dict[str, Any]:
    """Shared implementation for memory_get (class-based and @tool_define)."""
    session = session_factory()
    try:
        from sqlalchemy import select

        from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk

        query = (
            select(MemoryChunk)
            .where(
                MemoryChunk.source_id == source_id,
                MemoryChunk.project_id == project_id,
            )
            .order_by(MemoryChunk.chunk_index)
        )
        result = await session.execute(query)
        chunks = list(result.scalars().all())

        if not chunks:
            return {"error": f"No memory found for source_id: {source_id}"}

        items = [
            {
                "content": chunk.content,
                "category": chunk.category or "other",
                "chunk_index": chunk.chunk_index,
                "created_at": str(chunk.created_at) if chunk.created_at else "",
            }
            for chunk in chunks
        ]
        return {"source_id": source_id, "chunks": items, "total": len(items)}
    finally:
        await session.close()

class MemoryGetTool(AgentTool):
    """Retrieve the full content of a specific memory chunk by ID."""

    def __init__(
        self,
        session_factory: Callable[..., Any] | None = None,
        project_id: str = "",
    ) -> None:
        super().__init__(
            name="memory_get",
            description=(
                "Retrieve the full content of a specific memory entry by its source_id. "
                "Use after memory_search to get complete details of a result."
            ),
        )
        self._session_factory = session_factory
        self._project_id = project_id

    @override
    def get_parameters_schema(self) -> dict[str, Any]:
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

    @override
    async def execute(self, **kwargs: Any) -> str:
        source_id = kwargs.get("source_id", "")
        if not source_id:
            return json.dumps({"error": "source_id parameter is required"})

        if not self._session_factory:
            return json.dumps({"error": "Memory storage not available"})

        try:
            data = await _execute_memory_get(
                self._session_factory, self._project_id, source_id
            )
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning(f"Memory get failed: {e}")
            return json.dumps({"error": f"Failed to retrieve memory: {e}"})

# ---------------------------------------------------------------------------
# @tool_define version of MemorySearchTool
# ---------------------------------------------------------------------------

_memory_chunk_search: Any = None
_memory_graph_service: Any = None
_memory_project_id: str = ""


def configure_memory_search(
    chunk_search: Any,
    graph_service: Any = None,
    project_id: str = "",
) -> None:
    """Configure dependencies for the memory_search tool.

    Called at agent startup to inject search services.
    """
    global _memory_chunk_search, _memory_graph_service, _memory_project_id
    _memory_chunk_search = chunk_search
    _memory_graph_service = graph_service
    _memory_project_id = project_id


def _format_citations(results: list[dict[str, Any]]) -> None:
    """Add citation strings to result dicts, in-place."""
    for r in results:
        created = r.get("created_at", "")
        if isinstance(created, datetime):
            created = created.strftime("%Y-%m-%d")
        elif isinstance(created, str) and "T" in created:
            created = created.split("T")[0]
        r["citation"] = f"[{r['category']} | {r['source_type']}:{r['source_id'][:8]} | {created}]"


def _extract_graph_fields(
    gr: Any,
) -> tuple[str, float, str, str]:
    """Extract content, score, source_id, created_at from a graph result.

    Prefers memory_id over uuid for source_id so that memory_get can
    find the corresponding MemoryChunk (which uses memory.id as source_id).
    """
    if isinstance(gr, dict):
        content = gr.get("content", "") or gr.get("fact", "")
        score = gr.get("score", 0.5)
        uid = gr.get("memory_id", "") or gr.get("uuid", "")
        created = gr.get("created_at", "")
    else:
        content = getattr(gr, "fact", "") or getattr(gr, "content", "")
        score = getattr(gr, "score", 0.5)
        uid = getattr(gr, "memory_id", "") or getattr(gr, "uuid", "")
        created = getattr(gr, "created_at", "")
    return content, score, uid, created


async def _search_graph_for_tool(
    results: list[dict[str, Any]],
    query: str,
    max_results: int,
) -> None:
    """Search knowledge graph and append results in-place."""
    if _memory_graph_service is None:
        return
    try:
        graph_results = await _memory_graph_service.search(query, project_id=_memory_project_id)
        for gr in graph_results[: max_results - len(results)]:
            content, score, uid, created = _extract_graph_fields(gr)
            if content:
                results.append(
                    {
                        "content": content,
                        "score": round(float(score), 3),
                        "category": "fact",
                        "source_type": "knowledge_graph",
                        "source_id": str(uid),
                        "created_at": (str(created) if created else ""),
                    }
                )
    except Exception as e:
        logger.debug("Graph search failed (non-critical): %s", e)


@tool_define(
    name="memory_search",
    description=(
        "Search the project memory for relevant context. "
        "Use this BEFORE answering questions about prior work, "
        "decisions, user preferences, past conversations, "
        "or any information that may have been stored previously. "
        "Returns ranked results with source citations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": ("Search query describing what you want to find in memory."),
            },
            "max_results": {
                "type": "integer",
                "description": ("Maximum number of results to return (default: 5)."),
                "default": 5,
            },
            "category": {
                "type": "string",
                "description": ("Optional filter by category: preference, fact, decision, entity."),
                "enum": [
                    "preference",
                    "fact",
                    "decision",
                    "entity",
                ],
            },
        },
        "required": ["query"],
    },
    permission=None,
    category="memory",
)
async def memory_search_tool(
    ctx: ToolContext,
    *,
    query: str,
    max_results: int = 5,
    category: str | None = None,
) -> ToolResult:
    """Search project memory using hybrid retrieval."""
    _ = ctx  # reserved for future use
    if _memory_chunk_search is None:
        return ToolResult(
            output=json.dumps({"error": "Memory search not configured"}),
            is_error=True,
        )

    if not query:
        return ToolResult(
            output=json.dumps({"error": "query parameter is required"}),
            is_error=True,
        )

    results: list[dict[str, Any]] = []

    # Search memory chunks via hybrid search
    try:
        chunk_results = await _memory_chunk_search.search(
            query=query,
            project_id=_memory_project_id,
            limit=max_results,
            category=category,
        )
        for r in chunk_results:
            item = {
                "content": r.content,
                "score": round(r.score, 3),
                "category": r.category or "other",
                "source_type": r.source_type or "unknown",
                "source_id": r.source_id or "",
                "created_at": (str(r.created_at) if r.created_at else ""),
            }
            results.append(item)
    except Exception as e:
        logger.warning("Memory chunk search failed: %s", e)

    # Also search knowledge graph if available
    if _memory_graph_service and len(results) < max_results:
        await _search_graph_for_tool(results, query, max_results)

    # Format citations
    _format_citations(results)

    return ToolResult(
        output=json.dumps(
            {
                "results": results[:max_results],
                "total": len(results),
                "query": query,
            },
            ensure_ascii=False,
            default=str,
        )
    )


# ---------------------------------------------------------------------------
# @tool_define version of MemoryGetTool
# ---------------------------------------------------------------------------

_memget_session_factory: Callable[..., Any] | None = None
_memget_project_id: str = ""


def configure_memory_get(
    session_factory: Callable[..., Any],
    project_id: str = "",
) -> None:
    """Configure dependencies for the memory_get tool.

    Called at agent startup to inject the DB session factory.
    """
    global _memget_session_factory, _memget_project_id
    _memget_session_factory = session_factory
    _memget_project_id = project_id


@tool_define(
    name="memory_get",
    description=(
        "Retrieve the full content of a specific memory entry "
        "by its source_id. Use after memory_search to get "
        "complete details of a result."
    ),
    parameters={
        "type": "object",
        "properties": {
            "source_id": {
                "type": "string",
                "description": ("The source_id from a memory_search result."),
            },
        },
        "required": ["source_id"],
    },
    permission=None,
    category="memory",
)
async def memory_get_tool(
    ctx: ToolContext,
    *,
    source_id: str,
) -> ToolResult:
    """Retrieve full content of a memory entry by source_id."""
    _ = ctx  # reserved for future use
    if not source_id:
        return ToolResult(
            output=json.dumps({"error": "source_id parameter is required"}),
            is_error=True,
        )

    if _memget_session_factory is None:
        return ToolResult(
            output=json.dumps({"error": "Memory storage not available"}),
            is_error=True,
        )

    try:
        data = await _execute_memory_get(
            _memget_session_factory, _memget_project_id, source_id
        )
        is_err = "error" in data
        return ToolResult(
            output=json.dumps(data, ensure_ascii=False, default=str),
            is_error=is_err,
        )
    except Exception as e:
        logger.warning("Memory get failed: %s", e)
        return ToolResult(
            output=json.dumps({"error": f"Failed to retrieve memory: {e}"}),
            is_error=True,
        )


# ---------------------------------------------------------------------------
# MemoryCreateTool (class-based) + @tool_define memory_create_tool
# ---------------------------------------------------------------------------

_memcreate_session_factory: Callable[..., Any] | None = None
_memcreate_graph_service: Any = None
_memcreate_embedding_service: Any = None
_memcreate_project_id: str = ""
_memcreate_tenant_id: str = ""
_memcreate_user_id: str = ""

def configure_memory_create(
    session_factory: Callable[..., Any],
    graph_service: Any,
    project_id: str = "",
    tenant_id: str = "",
    user_id: str = "",
    embedding_service: Any = None,
) -> None:
    """Configure dependencies for the memory_create tool.

    Called at agent startup to inject the DB session factory and graph service.
    """
    global _memcreate_session_factory, _memcreate_graph_service
    global _memcreate_project_id, _memcreate_tenant_id, _memcreate_user_id
    global _memcreate_embedding_service
    _memcreate_session_factory = session_factory
    _memcreate_graph_service = graph_service
    _memcreate_embedding_service = embedding_service
    _memcreate_project_id = project_id
    _memcreate_tenant_id = tenant_id
    _memcreate_user_id = user_id


class MemoryCreateTool(AgentTool):
    """Create a new memory entry in the project knowledge base.

    Persists the memory to the database and adds an episode to the
    knowledge graph for entity extraction and relationship discovery.
    """

    def __init__(
        self,
        session_factory: Callable[..., Any] | None = None,
        graph_service: Any = None,
        project_id: str = "",
        tenant_id: str = "",
        user_id: str = "",
    ) -> None:
        super().__init__(
            name="memory_create",
            description=(
                "Create a new memory entry in the project knowledge base. "
                "Use this to persist important facts, user preferences, decisions, "
                "or any information that should be remembered for future conversations. "
                "The memory will be indexed and made searchable via memory_search."
            ),
        )
        self._session_factory = session_factory
        self._graph_service = graph_service
        self._project_id = project_id
        self._tenant_id = tenant_id
        self._user_id = user_id

    def set_runtime_context(self, ctx: ToolContext) -> None:
        """Receive per-request context from the processor adapter.

        This allows legacy class-based tools to access per-request fields
        (e.g. ``user_id``) that are only available in ``ToolContext``.
        """
        if ctx.user_id:
            self._user_id = ctx.user_id

    @override
    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "The content to store as a memory. "
                        "Be specific and include all relevant details."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": (
                        "A short descriptive title for this memory. "
                        "If omitted, one will be generated from the content."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": "Category of the memory.",
                    "enum": ["preference", "fact", "decision", "entity"],
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization.",
                },
            },
            "required": ["content"],
        }

    @override
    async def execute(self, **kwargs: Any) -> str:
        content = kwargs.get("content", "")
        title = kwargs.get("title", "")
        category = kwargs.get("category", "fact")
        tags: list[str] = kwargs.get("tags") or []

        if not content:
            return json.dumps({"error": "content parameter is required"})

        if not title:
            title = content[:80].strip()
            if len(content) > 80:
                title += "..."

        return await _execute_memory_create(
            content=content,
            title=title,
            category=category,
            tags=tags,
            session_factory=self._session_factory,
            graph_service=self._graph_service,
            project_id=self._project_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
        )


async def _execute_memory_create(
    *,
    content: str,
    title: str,
    category: str,
    tags: list[str],
    session_factory: Callable[..., Any] | None,
    graph_service: Any,
    project_id: str,
    tenant_id: str,
    user_id: str = "",
    embedding_service: Any = None,
) -> str:
    """Shared implementation for both class-based and @tool_define memory_create."""
    if not session_factory or not graph_service:
        return json.dumps({"error": "Memory creation not configured"})

    session = session_factory()
    try:
        from src.application.services.memory_service import MemoryService
        from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
            SqlMemoryRepository,
        )

        repo = SqlMemoryRepository(session)
        service = MemoryService(
            memory_repo=repo,
            graph_service=graph_service,
        )

        memory = await service.create_memory(
            title=title,
            content=content,
            project_id=project_id,
            user_id=user_id or "agent",
            tenant_id=tenant_id,
            content_type="text",
            tags=tags,
            metadata={"category": category, "source": "agent_tool"},
        )

        await session.commit()

        # Create a searchable MemoryChunk with embedding for vector search
        # Generate embedding inline so the chunk is immediately searchable
        try:
            from src.infrastructure.adapters.secondary.persistence.models import (
                MemoryChunk,
            )

            # Generate embedding for vector search (graceful degradation)
            embedding: list[float] | None = None
            emb_svc = embedding_service or _memcreate_embedding_service
            if emb_svc:
                try:
                    embedding = await emb_svc.embed_text(content)
                except Exception as emb_err:
                    logger.warning(
                        "memory_create: embedding generation failed, "+
                        "chunk will be saved without embedding: %s",
                        emb_err,
                    )

            chunk = MemoryChunk(
                id=str(uuid_mod.uuid4()),
                project_id=project_id,
                source_type="memory",
                source_id=memory.id,
                chunk_index=0,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                category=category,
                embedding=embedding,
                metadata_={"title": title, "tags": tags, "source": "agent_tool"},
            )
            session.add(chunk)
            await session.commit()
        except Exception as chunk_err:
            logger.warning("memory_create: failed to create searchable chunk: %s", chunk_err)

        logger.info(
            "memory_create: created memory %s for project %s",
            memory.id,
            project_id,
        )

        return json.dumps(
            {
                "status": "created",
                "memory_id": memory.id,
                "title": memory.title,
                "project_id": project_id,
                "processing_status": memory.processing_status,
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as e:
        logger.warning("memory_create failed: %s", e)
        await session.rollback()
        return json.dumps({"error": f"Failed to create memory: {e}"})
    finally:
        await session.close()


@tool_define(
    name="memory_create",
    description=(
        "Create a new memory entry in the project knowledge base. "
        "Use this to persist important facts, user preferences, decisions, "
        "or any information that should be remembered for future conversations. "
        "The memory will be indexed and made searchable via memory_search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": (
                    "The content to store as a memory. "
                    "Be specific and include all relevant details."
                ),
            },
            "title": {
                "type": "string",
                "description": (
                    "A short descriptive title for this memory. "
                    "If omitted, one will be generated from the content."
                ),
            },
            "category": {
                "type": "string",
                "description": "Category of the memory.",
                "enum": ["preference", "fact", "decision", "entity"],
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorization.",
            },
        },
        "required": ["content"],
    },
    permission=None,
    category="memory",
)
async def memory_create_tool(
    ctx: ToolContext,
    *,
    content: str,
    title: str = "",
    category: str = "fact",
    tags: list[str] | None = None,
) -> ToolResult:
    """Create a new memory entry in the project knowledge base."""
    user_id = ctx.user_id or ""
    if not content:
        return ToolResult(
            output=json.dumps({"error": "content parameter is required"}),
            is_error=True,
        )

    if not title:
        title = content[:80].strip()
        if len(content) > 80:
            title += "..."

    result = await _execute_memory_create(
        content=content,
        title=title,
        category=category,
        tags=tags or [],
        session_factory=_memcreate_session_factory,
        graph_service=_memcreate_graph_service,
        project_id=ctx.project_id or _memcreate_project_id,
        tenant_id=_memcreate_tenant_id,
        user_id=user_id,
    )

    is_error = '"error"' in result
    return ToolResult(output=result, is_error=is_error)


# ---------------------------------------------------------------------------
# @tool_define memory_update
# ---------------------------------------------------------------------------


async def _execute_memory_update(
    *,
    memory_id: str,
    title: str | None,
    content: str | None,
    tags: list[str] | None,
    metadata: dict[str, Any] | None,
    session_factory: Callable[..., Any] | None,
    graph_service: Any,
) -> str:
    """Shared implementation for memory_update tool."""
    if not session_factory or not graph_service:
        return json.dumps({"error": "Memory update not configured"})

    session = session_factory()
    try:
        from src.application.services.memory_service import MemoryService
        from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
            SqlMemoryRepository,
        )

        repo = SqlMemoryRepository(session)
        service = MemoryService(
            memory_repo=repo,
            graph_service=graph_service,
        )

        memory = await service.update_memory(
            memory_id=memory_id,
            title=title,
            content=content,
            tags=tags,
            metadata=metadata,
        )

        await session.commit()

        # Sync MemoryChunk rows so memory_get returns updated content
        try:
            from sqlalchemy import update as sa_update

            from src.infrastructure.adapters.secondary.persistence.models import (
                MemoryChunk,
            )

            update_values: dict[str, Any] = {}
            if content is not None:
                update_values["content"] = content
                update_values["content_hash"] = hashlib.sha256(
                    content.encode()
                ).hexdigest()
                # Regenerate embedding for updated content
                emb_svc = _memcreate_embedding_service
                if emb_svc:
                    try:
                        new_embedding = await emb_svc.embed_text(content)
                        if new_embedding is not None:
                            update_values["embedding"] = new_embedding
                    except Exception as emb_err:
                        logger.warning(
                            "memory_update: embedding re-generation failed, "
                            + "keeping old embedding: %s",
                            emb_err,
                        )
            if title is not None or tags is not None:
                # Rebuild metadata_ JSON with updated title/tags
                update_values["metadata_"] = {
                    "title": title if title is not None else memory.title,
                    "tags": tags if tags is not None else memory.tags,
                    "source": "agent_tool",
                }
            if update_values:
                stmt = (
                    sa_update(MemoryChunk)
                    .where(MemoryChunk.source_id == memory_id)
                    .values(**update_values)
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as chunk_err:
            logger.warning(
                "memory_update: failed to sync MemoryChunk: %s", chunk_err
            )

        logger.info(
            "memory_update: updated memory %s",
            memory.id,
        )

        return json.dumps(
            {
                "status": "updated",
                "memory_id": memory.id,
                "title": memory.title,
                "project_id": memory.project_id,
                "processing_status": memory.processing_status,
            },
            ensure_ascii=False,
            default=str,
        )
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.warning("memory_update failed: %s", e)
        await session.rollback()
        return json.dumps({"error": f"Failed to update memory: {e}"})
    finally:
        await session.close()


@tool_define(
    name="memory_update",
    description=(
        "Update an existing memory entry in the project knowledge base. "
        "Use this to correct, expand, or modify previously stored memories. "
        "If the content is changed, the memory will be reprocessed for "
        "entity extraction and relationship discovery."
    ),
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": (
                    "The ID of the memory to update. "
                    "Obtain this from memory_search or memory_create results."
                ),
            },
            "title": {
                "type": "string",
                "description": "New title for the memory. Leave unset to keep current title.",
            },
            "content": {
                "type": "string",
                "description": (
                    "New content for the memory. Leave unset to keep current content. "
                    "If changed, the memory will be reprocessed."
                ),
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New tags to replace existing ones. Leave unset to keep current tags.",
            },
            "metadata": {
                "type": "object",
                "description": "Additional metadata to merge into the memory. Leave unset to keep current.",
            },
        },
        "required": ["memory_id"],
    },
    permission=None,
    category="memory",
)
async def memory_update_tool(
    ctx: ToolContext,
    *,
    memory_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    """Update an existing memory entry in the project knowledge base."""
    _ = ctx  # reserved for future use
    if not memory_id:
        return ToolResult(
            output=json.dumps({"error": "memory_id parameter is required"}),
            is_error=True,
        )

    result = await _execute_memory_update(
        memory_id=memory_id,
        title=title,
        content=content,
        tags=tags,
        metadata=metadata,
        session_factory=_memcreate_session_factory,
        graph_service=_memcreate_graph_service,
    )

    is_error = '"error"' in result
    return ToolResult(output=result, is_error=is_error)


# ---------------------------------------------------------------------------
# @tool_define memory_delete
# ---------------------------------------------------------------------------


async def _execute_memory_delete(
    *,
    memory_id: str,
    session_factory: Callable[..., Any] | None,
    graph_service: Any,
) -> str:
    """Shared implementation for memory_delete tool."""
    if not session_factory or not graph_service:
        return json.dumps({"error": "Memory deletion not configured"})

    session = session_factory()
    try:
        from src.application.services.memory_service import MemoryService
        from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
            SqlMemoryRepository,
        )

        repo = SqlMemoryRepository(session)
        service = MemoryService(
            memory_repo=repo,
            graph_service=graph_service,
        )

        await service.delete_memory(memory_id=memory_id)

        await session.commit()

        # Also delete MemoryChunk rows (memory_get reads from this table)
        try:
            from sqlalchemy import delete as sa_delete

            from src.infrastructure.adapters.secondary.persistence.models import (
                MemoryChunk,
            )

            stmt = sa_delete(MemoryChunk).where(
                MemoryChunk.source_id == memory_id
            )
            await session.execute(stmt)
            await session.commit()
        except Exception as chunk_err:
            logger.warning(
                "memory_delete: failed to remove MemoryChunk rows: %s",
                chunk_err,
            )

        logger.info(
            "memory_delete: deleted memory %s",
            memory_id,
        )

        return json.dumps(
            {
                "status": "deleted",
                "memory_id": memory_id,
            },
            ensure_ascii=False,
        )
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.warning("memory_delete failed: %s", e)
        await session.rollback()
        return json.dumps({"error": f"Failed to delete memory: {e}"})
    finally:
        await session.close()


@tool_define(
    name="memory_delete",
    description=(
        "Delete a memory entry from the project knowledge base. "
        "This permanently removes the memory and cleans up associated "
        "entities and relationships from the knowledge graph. "
        "Use with caution - this action cannot be undone."
    ),
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": (
                    "The ID of the memory to delete. "
                    "Obtain this from memory_search or memory_create results."
                ),
            },
        },
        "required": ["memory_id"],
    },
    permission=None,
    category="memory",
)
async def memory_delete_tool(
    ctx: ToolContext,
    *,
    memory_id: str,
) -> ToolResult:
    """Delete a memory entry from the project knowledge base."""
    _ = ctx  # reserved for future use
    if not memory_id:
        return ToolResult(
            output=json.dumps({"error": "memory_id parameter is required"}),
            is_error=True,
        )

    result = await _execute_memory_delete(
        memory_id=memory_id,
        session_factory=_memcreate_session_factory,
        graph_service=_memcreate_graph_service,
    )

    is_error = '"error"' in result
    return ToolResult(output=result, is_error=is_error)
