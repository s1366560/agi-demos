"""
Hybrid search combining vector search and keyword search.

This module provides:
- Vector similarity search using Neo4j vector indices
- Fulltext keyword search using Neo4j fulltext indices
- RRF (Reciprocal Rank Fusion) for combining results
- MMR (Maximal Marginal Relevance) for diversity re-ranking
- Temporal decay for recency-aware scoring
- Query expansion with stop-word filtering for improved FTS
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
from src.infrastructure.graph.neo4j_client import Neo4jClient
from src.infrastructure.graph.schemas import HybridSearchResult, SearchResultItem
from src.infrastructure.memory.mmr import mmr_rerank
from src.infrastructure.memory.query_expansion import extract_keywords
from src.infrastructure.memory.temporal_decay import apply_temporal_decay

logger = logging.getLogger(__name__)

# Default RRF constant (higher = more weight to later ranks)
DEFAULT_RRF_K = 60

# Default weights for combining search types
DEFAULT_VECTOR_WEIGHT = 0.6
DEFAULT_KEYWORD_WEIGHT = 0.4


@dataclass
class GraphSearchConfig:
    """Configuration for graph hybrid search enhancements.

    Controls MMR diversity re-ranking, temporal decay, and query expansion.
    All enhancements are opt-in via enable flags.
    """

    enable_mmr: bool = True
    mmr_lambda: float = 0.7
    enable_temporal_decay: bool = True
    temporal_half_life_days: float = 30.0
    enable_query_expansion: bool = True


def _item_to_dict(item: SearchResultItem) -> dict:
    """Convert a SearchResultItem to a dict for MMR/temporal decay processing."""
    return {
        "uuid": item.uuid,
        "type": item.type,
        "name": item.name or "",
        "content": item.content or item.summary or item.name or "",
        "summary": item.summary or "",
        "score": item.score,
        "metadata": dict(item.metadata),
    }


def _dict_to_item(d: dict) -> SearchResultItem:
    """Convert a processed dict back to a SearchResultItem."""
    return SearchResultItem(
        type=d["type"],
        uuid=d["uuid"],
        name=d.get("name"),
        content=d.get("content") if d["type"] == "episode" else None,
        summary=d.get("summary") if d["type"] == "entity" else None,
        score=d.get("score", 0.0),
        metadata=d.get("metadata", {}),
    )


class HybridSearch:
    """
    Hybrid search engine combining vector and keyword search.

    Uses RRF (Reciprocal Rank Fusion) to combine results from:
    - Vector search: Semantic similarity using embeddings
    - Keyword search: Fulltext search using Neo4j indices

    Post-processing pipeline (when enabled via GraphSearchConfig):
    1. Query expansion: Extract keywords for improved FTS matching
    2. RRF fusion: Combine vector + keyword results
    3. Temporal decay: Down-weight older results
    4. MMR re-ranking: Balance relevance with diversity

    Example:
        config = GraphSearchConfig(enable_mmr=True, enable_temporal_decay=True)
        search = HybridSearch(neo4j_client, embedding_service, search_config=config)
        results = await search.search("machine learning applications", project_id="proj1")
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        embedding_service: EmbeddingService,
        vector_index_name: str = "entity_name_vector",
        fulltext_index_entities: str = "entity_name_summary",
        fulltext_index_episodes: str = "episodic_content",
        rrf_k: int = DEFAULT_RRF_K,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
        search_config: GraphSearchConfig | None = None,
    ) -> None:
        """
        Initialize hybrid search.

        Args:
            neo4j_client: Neo4j client for queries
            embedding_service: Service for generating query embeddings
            vector_index_name: Name of the vector index for entities
            fulltext_index_entities: Name of the fulltext index for entities
            fulltext_index_episodes: Name of the fulltext index for episodes
            rrf_k: RRF constant (default: 60)
            vector_weight: Weight for vector search results
            keyword_weight: Weight for keyword search results
            search_config: Configuration for MMR, temporal decay, and query expansion
        """
        self._neo4j_client = neo4j_client
        self._embedding_service = embedding_service
        self._vector_index_name = vector_index_name
        self._fulltext_index_entities = fulltext_index_entities
        self._fulltext_index_episodes = fulltext_index_episodes
        self._rrf_k = rrf_k
        self._vector_weight = vector_weight
        self._keyword_weight = keyword_weight
        self._search_config = search_config or GraphSearchConfig()

    async def search(
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
        include_episodes: bool = True,
        include_entities: bool = True,
    ) -> HybridSearchResult:
        """
        Perform hybrid search combining vector and keyword search.
        """
        if not query or not query.strip():
            return HybridSearchResult(items=[], total_results=0)
        fetch_limit = limit * 3 if self._search_config.enable_mmr else limit * 2

        expanded_query = self._expand_query(query)

        results = await self._run_searches(
            query, expanded_query, project_id, fetch_limit, include_episodes, include_entities
        )

        vector_entity_results, keyword_entity_results, episode_results = (
            self._collect_search_results(results, include_entities, include_episodes)
        )
        combined_entities = self._rrf_fusion(
            vector_entity_results,
            keyword_entity_results,
            vector_weight=self._vector_weight,
            keyword_weight=self._keyword_weight,
        )
        all_results = combined_entities + episode_results
        all_results.sort(key=lambda x: x.score, reverse=True)
        all_results = self._apply_post_processing(all_results)
        limited_results = all_results[:limit]
        return HybridSearchResult(
            items=limited_results,
            total_results=len(all_results),
            vector_results_count=len(vector_entity_results),
            keyword_results_count=len(keyword_entity_results) + len(episode_results),
        )

    def _expand_query(self, query: str) -> str:
        """Expand query with keywords if enabled."""
        if not self._search_config.enable_query_expansion:
            return query
        keywords = extract_keywords(query)
        if keywords:
            logger.debug(f"Query expanded: '{query}' -> keywords: {keywords}")
            return " ".join(keywords)
        return query

    async def _run_searches(
        self,
        query: str,
        expanded_query: str,
        project_id: str | None,
        fetch_limit: int,
        include_episodes: bool,
        include_entities: bool,
    ) -> list[Any]:
        """Run all search tasks in parallel."""
        tasks: list[Any] = []
        if include_entities:
            tasks.append(self._vector_search_entities(query, project_id, fetch_limit))
            tasks.append(self._keyword_search_entities(expanded_query, project_id, fetch_limit))
        if include_episodes:
            tasks.append(self._keyword_search_episodes(expanded_query, project_id, fetch_limit))
        return await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _collect_search_results(
        results: list[Any],
        include_entities: bool,
        include_episodes: bool,
    ) -> tuple[list[SearchResultItem], list[SearchResultItem], list[SearchResultItem]]:
        """Collect and categorize search results, handling errors."""
        vector_entity_results: list[SearchResultItem] = []
        keyword_entity_results: list[SearchResultItem] = []
        episode_results: list[SearchResultItem] = []
        idx = 0
        if include_entities:
            if not isinstance(results[idx], BaseException):
                vector_entity_results = results[idx]
            else:
                logger.warning(f"Vector search failed: {results[idx]}")
            idx += 1

            if not isinstance(results[idx], BaseException):
                keyword_entity_results = results[idx]
            else:
                logger.warning(f"Entity keyword search failed: {results[idx]}")
            idx += 1

        if include_episodes:
            if not isinstance(results[idx], BaseException):
                episode_results = results[idx]
            else:
                logger.warning(f"Episode keyword search failed: {results[idx]}")
        return vector_entity_results, keyword_entity_results, episode_results

    def _apply_post_processing(self, items: list[SearchResultItem]) -> list[SearchResultItem]:
        """Apply temporal decay and MMR re-ranking to search results.

        Pipeline order:
        1. Temporal decay (adjust scores based on age)
        2. Re-sort by decayed scores
        3. MMR re-ranking (balance relevance with diversity)

        Args:
            items: Search results after RRF fusion.

        Returns:
            Post-processed and re-ranked items.
        """
        if not items:
            return items

        # Convert to dicts for processing
        dicts = [_item_to_dict(item) for item in items]

        # 1. Temporal decay
        if self._search_config.enable_temporal_decay:
            now = datetime.now(UTC)
            for d in dicts:
                created_at_str = d["metadata"].get("created_at")
                if created_at_str:
                    try:
                        created_at = datetime.fromisoformat(created_at_str)
                        d["score"] = apply_temporal_decay(
                            d["score"],
                            created_at,
                            self._search_config.temporal_half_life_days,
                            now,
                        )
                    except (ValueError, TypeError):
                        pass  # Skip decay for items without valid timestamps

            # Re-sort after decay
            dicts.sort(key=lambda x: x.get("score", 0), reverse=True)

        # 2. MMR re-ranking for diversity
        if self._search_config.enable_mmr and len(dicts) > 1:
            dicts = mmr_rerank(
                dicts,
                lambda_=self._search_config.mmr_lambda,
                content_key="content",
                score_key="score",
            )

        # Convert back to SearchResultItem
        return [_dict_to_item(d) for d in dicts]

    async def vector_search(
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[SearchResultItem]:
        """
        Perform vector-only search on entities.

        Args:
            query: Search query
            project_id: Optional project filter
            limit: Maximum results

        Returns:
            List of SearchResultItem
        """
        return await self._vector_search_entities(query, project_id, limit)

    async def keyword_search(
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
        include_episodes: bool = True,
        include_entities: bool = True,
    ) -> list[SearchResultItem]:
        """
        Perform keyword-only search.

        Args:
            query: Search query
            project_id: Optional project filter
            limit: Maximum results
            include_episodes: Search episodes
            include_entities: Search entities

        Returns:
            List of SearchResultItem
        """
        # Apply query expansion for keyword search
        search_query = query
        if self._search_config.enable_query_expansion:
            keywords = extract_keywords(query)
            if keywords:
                search_query = " ".join(keywords)

        tasks = []

        if include_entities:
            tasks.append(self._keyword_search_entities(search_query, project_id, limit))

        if include_episodes:
            tasks.append(self._keyword_search_episodes(search_query, project_id, limit))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for result in results:
            if not isinstance(result, BaseException):
                all_results.extend(result)

        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:limit]

    async def _vector_search_entities(
        self,
        query: str,
        project_id: str | None,
        limit: int,
    ) -> list[SearchResultItem]:
        """
        Vector search on entity nodes.

        Args:
            query: Search query
            project_id: Project filter
            limit: Maximum results

        Returns:
            List of SearchResultItem
        """
        # Generate query embedding
        try:
            query_embedding = await self._embedding_service.embed_text(query)
        except Exception as e:
            logger.error(f"Failed to generate query embedding: {e}")
            return []

        # Validate embedding dimension
        expected_dim = getattr(self._embedding_service, "embedding_dim", None)
        if expected_dim and len(query_embedding) != expected_dim:
            logger.warning(
                f"Embedding dimension mismatch: got {len(query_embedding)}, expected {expected_dim}"
            )
            return []

        # Build query - request more results when filtering by project_id
        query_limit = limit * 2 if project_id else limit
        project_filter = ""
        params: dict[str, Any] = {
            "limit": query_limit,
            "query_embedding": query_embedding,
        }

        if project_id:
            project_filter = "WHERE node.project_id = $project_id"
            params["project_id"] = project_id

        cypher_query = f"""
            CALL db.index.vector.queryNodes(
                $index_name,
                $limit,
                $query_embedding
            )
            YIELD node, score
            {project_filter}
            RETURN node.uuid AS uuid,
                   node.name AS name,
                   node.summary AS summary,
                   coalesce(node.entity_type, 'Entity') AS entity_type,
                   node.created_at AS created_at,
                   score
            ORDER BY score DESC
            LIMIT $result_limit
        """

        # Try dimension-specific index first, then fall back to default
        query_dim = len(query_embedding)
        dimension_specific_index = f"entity_name_vector_{query_dim}D"
        params["result_limit"] = limit

        try:
            # First try dimension-specific index
            params["index_name"] = dimension_specific_index
            result = await self._neo4j_client.execute_query(cypher_query, **params)

            items = []
            for record in result.records:
                item = SearchResultItem(
                    type="entity",
                    uuid=record.get("uuid", ""),
                    name=record.get("name"),
                    summary=record.get("summary"),
                    score=float(record.get("score", 0)),
                    metadata={
                        "entity_type": record.get("entity_type"),
                        "search_type": "vector",
                        "created_at": record.get("created_at"),
                    },
                )
                items.append(item)

            return items

        except Exception as e:
            error_str = str(e)
            # If dimension-specific index not found, try default index
            if "no such vector schema index" in error_str.lower():
                try:
                    params["index_name"] = self._vector_index_name
                    result = await self._neo4j_client.execute_query(cypher_query, **params)
                    return [
                        SearchResultItem(
                            type="entity",
                            uuid=record.get("uuid", ""),
                            name=record.get("name"),
                            summary=record.get("summary"),
                            score=float(record.get("score", 0)),
                            metadata={
                                "entity_type": record.get("entity_type"),
                                "search_type": "vector",
                                "created_at": record.get("created_at"),
                            },
                        )
                        for record in result.records
                    ]
                except Exception:
                    pass  # Fall through to error handling below
            # Check for dimension mismatch errors
            if "dimensions" in error_str.lower() or "vector has" in error_str.lower():
                logger.warning(
                    f"Vector dimension mismatch detected. Falling back to keyword search. "
                    f"Error: {e}"
                )
                return []
            logger.error(f"Vector search query failed: {e}")
            return []

    async def _keyword_search_entities(
        self,
        query: str,
        project_id: str | None,
        limit: int,
    ) -> list[SearchResultItem]:
        """
        Keyword search on entity nodes using fulltext index.

        Args:
            query: Search query (may be pre-expanded via query expansion)
            project_id: Project filter
            limit: Maximum results

        Returns:
            List of SearchResultItem
        """
        # Escape special characters for fulltext search
        escaped_query = self._escape_fulltext_query(query)

        project_filter = ""
        params: dict[str, Any] = {
            "search_query": escaped_query,
            "limit": limit,
        }

        if project_id:
            project_filter = "WHERE node.project_id = $project_id"
            params["project_id"] = project_id

        cypher_query = f"""
            CALL db.index.fulltext.queryNodes($index_name, $search_query)
            YIELD node, score
            {project_filter}
            RETURN node.uuid AS uuid,
                   node.name AS name,
                   node.summary AS summary,
                   coalesce(node.entity_type, 'Entity') AS entity_type,
                   node.created_at AS created_at,
                   score
            ORDER BY score DESC
            LIMIT $limit
        """
        params["index_name"] = self._fulltext_index_entities

        try:
            result = await self._neo4j_client.execute_query(cypher_query, **params)

            items = []
            for record in result.records:
                item = SearchResultItem(
                    type="entity",
                    uuid=record.get("uuid", ""),
                    name=record.get("name"),
                    summary=record.get("summary"),
                    score=float(record.get("score", 0)),
                    metadata={
                        "entity_type": record.get("entity_type"),
                        "search_type": "keyword",
                        "created_at": record.get("created_at"),
                    },
                )
                items.append(item)

            return items

        except Exception as e:
            logger.error(f"Entity keyword search failed: {e}")
            return []

    async def _keyword_search_episodes(
        self,
        query: str,
        project_id: str | None,
        limit: int,
    ) -> list[SearchResultItem]:
        """
        Keyword search on episode nodes using fulltext index.

        Args:
            query: Search query (may be pre-expanded via query expansion)
            project_id: Project filter
            limit: Maximum results

        Returns:
            List of SearchResultItem
        """
        escaped_query = self._escape_fulltext_query(query)

        project_filter = ""
        params: dict[str, Any] = {
            "search_query": escaped_query,
            "limit": limit,
        }

        if project_id:
            project_filter = "WHERE node.project_id = $project_id"
            params["project_id"] = project_id

        cypher_query = f"""
            CALL db.index.fulltext.queryNodes($index_name, $search_query)
            YIELD node, score
            {project_filter}
            RETURN node.uuid AS uuid,
                   node.name AS name,
                   node.content AS content,
                   node.created_at AS created_at,
                   score
            ORDER BY score DESC
            LIMIT $limit
        """
        params["index_name"] = self._fulltext_index_episodes

        try:
            result = await self._neo4j_client.execute_query(cypher_query, **params)

            items = []
            for record in result.records:
                item = SearchResultItem(
                    type="episode",
                    uuid=record.get("uuid", ""),
                    name=record.get("name"),
                    content=record.get("content"),
                    score=float(record.get("score", 0)),
                    metadata={
                        "search_type": "keyword",
                        "created_at": record.get("created_at"),
                    },
                )
                items.append(item)

            return items

        except Exception as e:
            logger.error(f"Episode keyword search failed: {e}")
            return []

    def _rrf_fusion(
        self,
        vector_results: list[SearchResultItem],
        keyword_results: list[SearchResultItem],
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
    ) -> list[SearchResultItem]:
        """
        Combine results using Reciprocal Rank Fusion (RRF).

        RRF formula: score = sum(weight / (k + rank))

        Args:
            vector_results: Results from vector search
            keyword_results: Results from keyword search
            vector_weight: Weight for vector results
            keyword_weight: Weight for keyword results

        Returns:
            Combined and re-ranked results
        """
        # Build score maps
        scores: dict[str, float] = {}
        items_map: dict[str, SearchResultItem] = {}

        # Process vector results
        for rank, item in enumerate(vector_results, start=1):
            uuid = item.uuid
            rrf_score = vector_weight * (1.0 / (self._rrf_k + rank))
            scores[uuid] = scores.get(uuid, 0) + rrf_score
            if uuid not in items_map:
                items_map[uuid] = item

        # Process keyword results
        for rank, item in enumerate(keyword_results, start=1):
            uuid = item.uuid
            rrf_score = keyword_weight * (1.0 / (self._rrf_k + rank))
            scores[uuid] = scores.get(uuid, 0) + rrf_score
            if uuid not in items_map:
                items_map[uuid] = item

        # Create combined results with new scores
        combined = []
        for uuid, score in scores.items():
            item = items_map[uuid]
            # Merge metadata: prefer vector result's metadata, add rrf_score
            merged_metadata = {**item.metadata, "rrf_score": score}
            combined_item = SearchResultItem(
                type=item.type,
                uuid=item.uuid,
                name=item.name,
                content=item.content,
                summary=item.summary,
                score=score,
                metadata=merged_metadata,
            )
            combined.append(combined_item)

        # Sort by RRF score
        combined.sort(key=lambda x: x.score, reverse=True)

        return combined

    def _escape_fulltext_query(self, query: str) -> str:
        """
        Escape special characters for Neo4j fulltext search.

        Args:
            query: Raw query string

        Returns:
            Escaped query string
        """
        # Escape backslash first to avoid double-escaping other characters
        escaped = query.replace("\\", "\\\\")

        # Characters that need escaping in Lucene fulltext queries
        special_chars = [
            "+",
            "-",
            "&&",
            "||",
            "!",
            "(",
            ")",
            "{",
            "}",
            "[",
            "]",
            "^",
            '"',
            "~",
            "*",
            "?",
            ":",
            "/",
        ]

        for char in special_chars:
            escaped = escaped.replace(char, f"\\{char}")

        return escaped


class EpisodeRetriever:
    """
    Retriever for episodes with various filtering options.
    """

    def __init__(self, neo4j_client: Neo4jClient) -> None:
        """
        Initialize episode retriever.

        Args:
            neo4j_client: Neo4j client
        """
        self._neo4j_client = neo4j_client

    async def retrieve_by_uuid(
        self,
        uuid: str,
    ) -> dict[str, Any] | None:
        """
        Retrieve a single episode by UUID.

        Args:
            uuid: Episode UUID

        Returns:
            Episode dict or None
        """
        query = """
            MATCH (e:Episodic {uuid: $uuid})
            RETURN e
        """

        result = await self._neo4j_client.execute_query(query, uuid=uuid)

        if result.records and len(result.records) > 0:
            return dict(result.records[0]["e"])
        return None

    async def retrieve_recent(
        self,
        project_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Retrieve recent episodes for a project.

        Args:
            project_id: Project ID
            limit: Maximum number of episodes

        Returns:
            List of episode dicts
        """
        query = """
            MATCH (e:Episodic {project_id: $project_id})
            RETURN e
            ORDER BY e.created_at DESC
            LIMIT $limit
        """

        result = await self._neo4j_client.execute_query(query, project_id=project_id, limit=limit)

        return [dict(record["e"]) for record in result.records]

    async def retrieve_by_memory_id(
        self,
        memory_id: str,
    ) -> dict[str, Any] | None:
        """
        Retrieve episode by memory ID.

        Args:
            memory_id: Memory ID

        Returns:
            Episode dict or None
        """
        query = """
            MATCH (e:Episodic {memory_id: $memory_id})
            RETURN e
        """

        result = await self._neo4j_client.execute_query(query, memory_id=memory_id)

        if result.records and len(result.records) > 0:
            return dict(result.records[0]["e"])
        return None

    async def retrieve_with_entities(
        self,
        uuid: str,
    ) -> dict[str, Any]:
        """
        Retrieve episode with its mentioned entities.

        Args:
            uuid: Episode UUID

        Returns:
            Dict with 'episode' and 'entities' keys
        """
        query = """
            MATCH (e:Episodic {uuid: $uuid})
            OPTIONAL MATCH (e)-[:MENTIONS]->(entity:Entity)
            RETURN e,
                   collect(entity) AS entities
        """

        result = await self._neo4j_client.execute_query(query, uuid=uuid)

        if not result.records or len(result.records) == 0:
            return {"episode": None, "entities": []}

        record = result.records[0]
        episode = dict(record["e"]) if record["e"] else None
        entities = [dict(e) for e in record["entities"]] if record["entities"] else []

        return {"episode": episode, "entities": entities}
