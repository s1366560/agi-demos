"""
Native Graph Adapter implementing GraphServicePort without Graphiti dependency.

This adapter provides a self-researched knowledge graph system that:
- Extracts entities and relationships using LLM
- Stores knowledge in Neo4j
- Provides hybrid search (vector + keyword)
- Supports community detection with Louvain algorithm
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast, override
from uuid import uuid4

from src.domain.model.graph.dtos import (
    GraphCommunityDTO,
    GraphEntityDTO,
    GraphExportDTO,
    GraphGraphDataDTO,
    GraphNodeDTO,
    GraphRelationshipDTO,
    GraphSearchHit,
)
from src.domain.model.memory.episode import Episode
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.queue_port import QueuePort

from .community.community_updater import CommunityUpdater
from .community.louvain_detector import LouvainDetector
from .embedding.embedding_service import EmbeddingService, NullEmbeddingService
from .extraction.entity_extractor import EntityExtractor
from .extraction.reflexion import ReflexionChecker
from .extraction.relationship_extractor import RelationshipExtractor
from .neo4j_client import Neo4jClient, _validate_identifier
from .schemas import (
    AddEpisodeResult,
    EntityEdge,
    EntityNode,
    EpisodeStatus,
    EpisodeType,
    EpisodicEdge,
    EpisodicNode,
)
from .search.hybrid_search import GraphSearchConfig, HybridSearch

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.graph.distributed_transaction_coordinator import (
        DistributedTransactionCoordinator,
    )

# Cache TTL for embedding dimension checks (seconds)
EMBEDDING_DIM_CACHE_TTL = 10


def _decode_attributes(value: Any) -> dict[str, Any]:  # noqa: ANN401
    """Decode a graph entity's ``attributes`` property into a dict.

    Neo4j may store it as a map, a JSON string, or absent. Mirrors the
    ``_decode_graph_json_property`` helper formerly inlined in the memories router.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _normalize_embedding_result(result: Any) -> list[float]:  # noqa: ANN401
    if isinstance(result, list) and result and isinstance(result[0], list):
        return cast(list[float], result[0])
    return cast(list[float], result)


async def _create_embedding_from_embedder(embedder: Any, text: str) -> list[float]:  # noqa: ANN401
    """Create an embedding vector from text via an embedder, normalizing the result.

    Supports both ``embed_text`` and ``create`` embedder interfaces.
    """
    if hasattr(embedder, "embed_text"):
        return _normalize_embedding_result(await embedder.embed_text(text))
    if hasattr(embedder, "create"):
        try:
            return _normalize_embedding_result(await embedder.create(input_data=text))
        except TypeError:
            return _normalize_embedding_result(await embedder.create(text))
    raise RuntimeError("Embedding provider not available")


class NativeGraphAdapter(GraphStorePort):
    """
    Native graph adapter implementing GraphStorePort.

    This adapter provides a complete knowledge graph system without
    depending on Graphiti, using self-researched implementations for:
    - Entity extraction (LLM-based)
    - Relationship discovery (LLM-based)
    - Hybrid search (vector + keyword + RRF)
    - Community detection (Louvain algorithm)

    It is the reference implementation of ``GraphStorePort`` and is the only
    backend today; it will be registered under the ``GraphBackendRegistry``
    as engine ``"neo4j"`` in Phase 3. New backends (ArcadeDB, AGE) should
    subclass ``GraphStorePort`` directly rather than this class.

    Example:
        adapter = NativeGraphAdapter(
            neo4j_client=client,
            llm_client=llm,
            embedding_service=embedder,
            queue_port=queue,
        )
        episode = await adapter.add_episode(episode)
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        llm_client: LLMClient,
        embedding_service: EmbeddingService,
        queue_port: QueuePort | None = None,
        enable_reflexion: bool = True,
        reflexion_max_iterations: int = 2,
        auto_clear_embeddings: bool = True,
    ) -> None:
        """
        Initialize native graph adapter.

        Args:
            neo4j_client: Neo4j client for graph operations
            llm_client: LLM client for entity/relationship extraction
            embedding_service: Service for generating embeddings
            queue_port: Optional queue port for async processing
            enable_reflexion: Enable reflexion iteration for entity extraction
            reflexion_max_iterations: Max reflexion iterations (default: 2)
            auto_clear_embeddings: Auto-clear embeddings on dimension mismatch
        """
        self._neo4j_client = neo4j_client
        self._llm_client = llm_client
        self._embedding_service = embedding_service
        self._queue_port = queue_port
        self._enable_reflexion = enable_reflexion
        self._reflexion_max_iterations = reflexion_max_iterations
        self._auto_clear_embeddings = auto_clear_embeddings
        # Optional Redis client for CachedEmbeddingService
        self._redis_client: Any | None = None

        # Lazily initialized components
        self._entity_extractor: EntityExtractor | None = None
        self._relationship_extractor: RelationshipExtractor | None = None
        self._reflexion_checker: ReflexionChecker | None = None
        self._hybrid_search: HybridSearch | None = None
        self._louvain_detector: LouvainDetector | None = None
        self._community_updater: CommunityUpdater | None = None

        # Cache for embedding dimension checks
        self._embedding_dim_cache: dict[str, Any] = {"value": None, "expiry": None}

        # Optional distributed transaction coordinator
        self._transaction_coordinator: Any | None = None

    @property
    def client(self) -> Neo4jClient:
        """Get the underlying Neo4j client (internal; lifecycle/close only).

        Prefer the typed ``GraphStorePort`` primitives. This remains for the
        startup/shutdown lifecycle and is intentionally NOT a raw-driver escape
        hatch for routers.
        """
        return self._neo4j_client

    async def close(self) -> None:
        """Close the underlying graph backend connection (lifecycle hook)."""
        await self._neo4j_client.close()

    @property
    def embedder(self) -> EmbeddingService:
        """Get the embedding service (used by embedding-maintenance primitives)."""
        return self._embedding_service

    @property
    def llm_client(self) -> LLMClient:
        """Get the LLM client (for compatibility with legacy AI tool routes)."""
        return self._llm_client

    @property
    def community_updater(self) -> CommunityUpdater:
        """Get the community updater (lazily initialized)."""
        return self._get_community_updater()

    def set_transaction_coordinator(self, coordinator: DistributedTransactionCoordinator) -> None:
        """
        Set the distributed transaction coordinator.

        Args:
            coordinator: DistributedTransactionCoordinator instance
        """
        self._transaction_coordinator = coordinator

    def set_redis_client(self, redis_client: Redis) -> None:
        """
        Set the Redis client for cached embedding support.

        When set, HybridSearch will wrap the embedding service with
        CachedEmbeddingService for L1+Redis caching of embeddings.

        Should be called after initialization when Redis becomes available.

        Args:
            redis_client: Redis client instance for L2 caching
        """
        self._redis_client = redis_client
        # Reset hybrid search so it gets recreated with cached embeddings
        self._hybrid_search = None
        logger.info(
            "Redis client set on NativeGraphAdapter; hybrid search will use cached embeddings"
        )

    def get_transaction_coordinator(self) -> DistributedTransactionCoordinator | None:
        """Get the current transaction coordinator."""
        return self._transaction_coordinator

    def _get_entity_extractor(self) -> EntityExtractor:
        """Get or create entity extractor."""
        if self._entity_extractor is None:
            self._entity_extractor = EntityExtractor(
                llm_client=self._llm_client,
                embedding_service=self._embedding_service,
            )
        return self._entity_extractor

    def _get_relationship_extractor(self) -> RelationshipExtractor:
        """Get or create relationship extractor."""
        if self._relationship_extractor is None:
            self._relationship_extractor = RelationshipExtractor(
                llm_client=self._llm_client,
            )
        return self._relationship_extractor

    def _get_reflexion_checker(self) -> ReflexionChecker:
        """Get or create reflexion checker."""
        if self._reflexion_checker is None:
            self._reflexion_checker = ReflexionChecker(
                llm_client=self._llm_client,
                embedding_service=self._embedding_service,
            )
        return self._reflexion_checker

    def _get_hybrid_search(self) -> HybridSearch:
        """Get or create hybrid search with optional cached embeddings."""
        if self._hybrid_search is None:
            embedding_service: Any = self._embedding_service

            # Wrap with CachedEmbeddingService if Redis is available
            if self._redis_client is not None:
                from src.infrastructure.memory.cached_embedding import CachedEmbeddingService

                embedding_service = CachedEmbeddingService(
                    embedding_service=self._embedding_service,
                    redis_client=self._redis_client,
                )
                logger.debug("HybridSearch using CachedEmbeddingService")
            self._hybrid_search = HybridSearch(
                neo4j_client=self._neo4j_client,
                embedding_service=embedding_service,
                search_config=GraphSearchConfig(),
            )
        return self._hybrid_search

    def _get_louvain_detector(self) -> LouvainDetector:
        """Get or create Louvain community detector."""
        if self._louvain_detector is None:
            self._louvain_detector = LouvainDetector(
                neo4j_client=self._neo4j_client,
                use_gds=True,  # Try GDS first, fall back to networkx
                min_community_size=2,
            )
        return self._louvain_detector

    def _get_community_updater(self) -> CommunityUpdater:
        """Get or create community updater."""
        if self._community_updater is None:
            self._community_updater = CommunityUpdater(
                neo4j_client=self._neo4j_client,
                llm_client=self._llm_client,
                louvain_detector=self._get_louvain_detector(),
            )
        return self._community_updater

    async def _check_embedding_dimension(self, force: bool = False) -> None:
        """
        Check embedding dimension compatibility.

        Uses a short-lived cache (10 seconds) to reduce Neo4j queries while
        still detecting provider switches reasonably quickly.

        Args:
            force: Bypass cache and force check
        """
        try:
            # Skip dimension check entirely for NullEmbeddingService
            if isinstance(self._embedding_service, NullEmbeddingService):
                return
            current_dim = self._embedding_service.embedding_dim

            # Check cache first (unless forced)
            now = datetime.now(UTC)
            if not force:
                cache_value = self._embedding_dim_cache.get("value")
                cache_expiry = self._embedding_dim_cache.get("expiry")

                if (
                    cache_value is not None
                    and cache_expiry is not None
                    and now < cache_expiry
                    and cache_value == current_dim
                ):
                    logger.debug(f"Using cached embedding dimension: {current_dim}D")
                    return

            # Get existing embedding dimension from Neo4j
            existing_dim = await self._get_existing_embedding_dimension()

            if existing_dim is None:
                logger.debug(f"No existing embeddings found. Current provider uses {current_dim}D.")

                self._embedding_dim_cache = {
                    "value": current_dim,
                    "expiry": now + timedelta(seconds=EMBEDDING_DIM_CACHE_TTL),
                }
                return

            if existing_dim == current_dim:
                logger.debug(f"Embedding dimensions compatible: {current_dim}D")

                self._embedding_dim_cache = {
                    "value": current_dim,
                    "expiry": now + timedelta(seconds=EMBEDDING_DIM_CACHE_TTL),
                }
                return

            # Dimension mismatch detected
            logger.warning(
                f"EMBEDDING DIMENSION MISMATCH DETECTED!\n"
                f"  - Existing embeddings in Neo4j: {existing_dim}D\n"
                f"  - Current embedder: {current_dim}D"
            )

            # Clear cache on mismatch
            self._embedding_dim_cache = {"value": None, "expiry": None}

            if self._auto_clear_embeddings:
                logger.info(f"Auto-clearing {existing_dim}D embeddings...")
                cleared_count = await self._clear_embeddings_by_dimension(existing_dim)
                logger.info(
                    f"Successfully cleared {cleared_count} embeddings. "
                    f"New embeddings will be created at {current_dim}D as needed."
                )

                self._embedding_dim_cache = {
                    "value": current_dim,
                    "expiry": now + timedelta(seconds=EMBEDDING_DIM_CACHE_TTL),
                }
            else:
                logger.warning(
                    "Auto-clear is disabled. Please manually clear embeddings or set "
                    "AUTO_CLEAR_MISMATCHED_EMBEDDINGS=True"
                )

        except Exception as e:
            logger.error(
                "Failed to check embedding dimension: error_type=%s",
                type(e).__name__,
            )

    async def _get_existing_embedding_dimension(self) -> int | None:
        """Get the dimension of existing embeddings in Neo4j.

        First checks embedding_dim property, then falls back to computing
        from the actual vector size.
        """
        # First try to get from embedding_dim property (faster)
        query_dim = """
            MATCH (n:Entity)
            WHERE n.embedding_dim IS NOT NULL
            WITH n LIMIT 1
            RETURN n.embedding_dim AS dim
        """
        try:
            result = await self._neo4j_client.execute_query(query_dim)
            if result.records and len(result.records) > 0 and result.records[0]["dim"]:
                return cast(int | None, result.records[0]["dim"])
        except Exception as e:
            logger.debug(
                "Failed to get embedding_dim property: error_type=%s",
                type(e).__name__,
            )

        # Fallback: compute from actual vector size
        query_size = """
            MATCH (n:Entity)
            WHERE n.name_embedding IS NOT NULL
            WITH n LIMIT 1
            RETURN size(n.name_embedding) AS dim
        """
        try:
            result = await self._neo4j_client.execute_query(query_size)
            if result.records and len(result.records) > 0:
                return cast(int | None, result.records[0]["dim"])
        except Exception as e:
            logger.warning(
                "Failed to get existing embedding dimension: error_type=%s",
                type(e).__name__,
            )
        return None

    async def _clear_embeddings_by_dimension(self, dimension: int) -> int:
        """
        Clear embeddings with the specified dimension.

        Args:
            dimension: Dimension of embeddings to clear

        Returns:
            Number of embeddings cleared
        """
        query = """
            MATCH (n:Entity)
            WHERE n.name_embedding IS NOT NULL AND size(n.name_embedding) = $dimension
            REMOVE n.name_embedding
            RETURN count(n) AS cleared
        """
        try:
            result = await self._neo4j_client.execute_query(query, dimension=dimension)
            if result.records and len(result.records) > 0:
                return cast(int, result.records[0]["cleared"])
        except Exception as e:
            logger.error("Failed to clear embeddings: error_type=%s", type(e).__name__)
        return 0

    @override
    async def add_episode(self, episode: Episode) -> Episode:
        """
        Add an episode to the knowledge graph.

        This method:
        1. Creates the Episodic node in Neo4j
        2. Queues the episode for async processing (entity extraction, etc.)

        Args:
            episode: Episode domain object

        Returns:
            The episode (unchanged)
        """
        try:
            # Check embedding dimension compatibility
            await self._check_embedding_dimension()

            group_id = episode.project_id or "global"

            # Create EpisodicNode
            episodic_node = EpisodicNode(
                uuid=episode.id,
                name=episode.name or episode.id,
                content=episode.content,
                source_description=episode.source_type.value,
                source=EpisodeType.TEXT,
                created_at=datetime.now(UTC),
                valid_at=episode.valid_at or datetime.now(UTC),
                group_id=group_id,
                tenant_id=episode.tenant_id,
                project_id=episode.project_id,
                user_id=episode.user_id,
                memory_id=episode.metadata.get("memory_id"),
                status=EpisodeStatus.PROCESSING,
            )

            # Save to Neo4j
            query = """
                MERGE (e:Episodic {uuid: $uuid})
                SET e:Node,
                    e.name = $name,
                    e.content = $content,
                    e.source_description = $source_description,
                    e.source = $source,
                    e.created_at = datetime($created_at),
                    e.valid_at = datetime($valid_at),
                    e.group_id = $group_id,
                    e.tenant_id = $tenant_id,
                    e.project_id = $project_id,
                    e.user_id = $user_id,
                    e.memory_id = $memory_id,
                    e.status = $status
            """

            props = episodic_node.to_neo4j_properties()
            await self._neo4j_client.execute_query(
                query,
                uuid=props["uuid"],
                name=props["name"],
                content=props["content"],
                source_description=props["source_description"],
                source=props["source"],
                created_at=props["created_at"],
                valid_at=props["valid_at"],
                group_id=props["group_id"],
                tenant_id=props["tenant_id"],
                project_id=props["project_id"],
                user_id=props["user_id"],
                memory_id=props["memory_id"],
                status=props["status"],
            )

            # Queue for async processing
            if self._queue_port:
                await self._queue_port.add_episode(
                    group_id=group_id,
                    name=episode.name or episode.id,
                    content=episode.content,
                    source_description=episode.source_type.value,
                    episode_type=EpisodeType.TEXT.value,
                    uuid=episode.id,
                    tenant_id=episode.tenant_id,
                    project_id=episode.project_id,
                    user_id=episode.user_id,
                    memory_id=episode.metadata.get("memory_id"),
                )
            else:
                logger.info(
                    "QueuePort not configured. Processing episode %s synchronously.",
                    episode.id,
                )
                _ = await self.process_episode(
                    episode_uuid=episode.id,
                    content=episode.content,
                    project_id=episode.project_id,
                    tenant_id=episode.tenant_id,
                    user_id=episode.user_id,
                )

            return episode

        except Exception as e:
            logger.error("Failed to add episode: error_type=%s", type(e).__name__)
            raise

    async def process_episode(
        self,
        episode_uuid: str,
        content: str,
        project_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        excluded_entity_types: list[str] | None = None,
    ) -> AddEpisodeResult:
        """
        Process an episode: extract entities, relationships, and update graph.

        This is called by the background worker after the episode is created.

        Args:
            episode_uuid: UUID of the episode
            content: Episode content to process
            project_id: Project ID
            tenant_id: Tenant ID
            user_id: User ID
            excluded_entity_types: List of entity types to exclude from extraction

        Returns:
            AddEpisodeResult with extraction results
        """
        try:
            # Check embedding dimension
            await self._check_embedding_dimension()

            # 0. Load project schema context (Graphiti-compatible)
            schema_context = await self._load_schema_context(project_id)
            entity_types_context = schema_context["entity_types_context"]
            entity_type_id_to_name = schema_context["entity_type_id_to_name"]
            edge_type_map = schema_context["edge_type_map"]

            logger.debug(
                f"Loaded schema context: {len(entity_types_context)} entity types, "
                f"{len(edge_type_map)} edge type mappings"
            )

            # 1. Extract entities with type context
            extractor = self._get_entity_extractor()
            entities = await extractor.extract(
                content=content,
                entity_types_context=entity_types_context,
                entity_type_id_to_name=entity_type_id_to_name,
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )

            # 2. Apply reflexion if enabled
            if self._enable_reflexion and entities:
                reflexion_checker = self._get_reflexion_checker()
                missed_entities = await reflexion_checker.check_missed_entities(
                    content=content,
                    extracted_entities=[e.model_dump() for e in entities],
                    entity_types_context=entity_types_context,
                    entity_type_id_to_name=entity_type_id_to_name,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                if missed_entities:
                    logger.info(f"Reflexion found {len(missed_entities)} additional entities")
                    entities.extend(missed_entities)

            # 3. Filter excluded entity types (Graphiti-compatible)
            if excluded_entity_types and entities:
                excluded_set = set(excluded_entity_types)
                original_count = len(entities)
                entities = [e for e in entities if e.entity_type not in excluded_set]
                filtered_count = original_count - len(entities)
                if filtered_count > 0:
                    logger.info(
                        f"Filtered {filtered_count} entities with excluded types: "
                        f"{excluded_entity_types}"
                    )

            # 4. Deduplicate against existing entities without re-extracting.
            existing_entities = await self._get_existing_entities(project_id)
            unique_entities, dedup_map = await extractor.deduplicate_entity_nodes(
                new_entities=entities,
                existing_entities=existing_entities,
            )
            final_entities = self._resolve_mentioned_entities(
                unique_entities=unique_entities,
                duplicate_map=dedup_map,
                existing_entities=existing_entities,
            )

            # 5. Save entities to Neo4j
            entity_edges: list[EpisodicEdge] = []
            for entity in unique_entities:
                # Save entity node
                await self._neo4j_client.save_node(
                    labels=entity.get_labels(),
                    uuid=entity.uuid,
                    properties=entity.to_neo4j_properties(),
                )

            for entity in final_entities:
                # Create MENTIONS edge from episode to entity
                edge = EpisodicEdge(
                    source_uuid=episode_uuid,
                    target_uuid=entity.uuid,
                    relationship_type="MENTIONS",
                )
                entity_edges.append(edge)

                await self._neo4j_client.save_edge(
                    from_uuid=episode_uuid,
                    to_uuid=entity.uuid,
                    relationship_type="MENTIONS",
                    properties=edge.to_neo4j_properties(),
                )

            # 6. Extract relationships with edge type constraints
            relationship_extractor = self._get_relationship_extractor()
            relationships = await relationship_extractor.extract_from_entity_nodes(
                content=content,
                entity_nodes=final_entities,
                edge_type_map=edge_type_map if edge_type_map else None,
                episode_uuid=episode_uuid,
            )

            # 7. Save relationships to Neo4j
            for rel in relationships:
                await self._save_entity_relationship(rel)

            # 7.5 Save discovered types to PostgreSQL
            if project_id:
                await self._save_discovered_types(
                    project_id=project_id,
                    entities=final_entities,
                    relationships=relationships,
                    existing_entity_types={ctx["entity_type_name"] for ctx in entity_types_context},
                )

            # 8. Update episode status
            await self._update_episode_status(
                episode_uuid=episode_uuid,
                status=EpisodeStatus.SYNCED,
                entity_edges=[edge.uuid for edge in entity_edges],
            )

            # 9. Get episode node for result
            episode_data = await self._neo4j_client.find_node_by_uuid(
                uuid=episode_uuid, labels=["Episodic"]
            )
            episode_node = EpisodicNode(
                uuid=episode_uuid,
                name=episode_data.get("name", episode_uuid) if episode_data else episode_uuid,
                content=content,
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )

            return AddEpisodeResult(
                episode=episode_node,
                nodes=final_entities,
                edges=relationships,
                episodic_edges=entity_edges,
                communities=[],  # Communities updated separately
                community_edges=[],
            )

        except Exception as e:
            logger.error("Failed to process episode: error_type=%s", type(e).__name__)
            # Update status to failed
            await self._update_episode_status(episode_uuid, EpisodeStatus.FAILED)
            raise

    async def _load_schema_context(self, project_id: str | None) -> dict[str, Any]:
        """Load project-specific graph schema context for extraction."""
        from src.infrastructure.adapters.secondary.schema.dynamic_schema import (
            get_project_schema_context,
        )

        return cast(dict[str, Any], await get_project_schema_context(project_id))

    @staticmethod
    def _resolve_mentioned_entities(
        *,
        unique_entities: list[EntityNode],
        duplicate_map: dict[str, str],
        existing_entities: list[EntityNode],
    ) -> list[EntityNode]:
        """Return unique entities plus existing graph nodes matched during dedupe."""
        mentioned_by_uuid = {entity.uuid: entity for entity in unique_entities}
        existing_by_uuid = {entity.uuid: entity for entity in existing_entities}

        for existing_uuid in duplicate_map.values():
            existing_entity = existing_by_uuid.get(existing_uuid)
            if existing_entity is not None:
                mentioned_by_uuid[existing_uuid] = existing_entity

        return list(mentioned_by_uuid.values())

    async def _save_entity_relationship(self, relationship: EntityEdge) -> None:
        """Save an entity relationship while preserving all supporting episodes."""
        _validate_identifier(relationship.relationship_type, "relationship type")
        properties = relationship.to_neo4j_properties()
        for key in properties:
            _validate_identifier(key, "property key")

        query = f"""
            MATCH (from {{uuid: $from_uuid}})
            MATCH (to {{uuid: $to_uuid}})
            MERGE (from)-[r:{relationship.relationship_type}]->(to)
            SET r.uuid = coalesce(r.uuid, $uuid),
                r.relationship_type = $relationship_type,
                r.fact = $fact,
                r.summary = $summary,
                r.weight = $weight,
                r.created_at = coalesce(r.created_at, $created_at),
                r.updated_at = datetime($updated_at),
                r.attributes = $attributes,
                r.episodes = reduce(
                    existing = coalesce(r.episodes, []),
                    episode_id IN $episodes |
                    CASE
                        WHEN episode_id IN existing THEN existing
                        ELSE existing + [episode_id]
                    END
                )
        """
        optional_datetime_fields = ("valid_at", "invalid_at", "expired_at")
        for field in optional_datetime_fields:
            if field in properties:
                query += f", r.{field} = ${field}"
        if "relationship_embedding" in properties:
            query += ", r.relationship_embedding = $relationship_embedding"

        params: dict[str, Any] = {
            "from_uuid": relationship.source_uuid,
            "to_uuid": relationship.target_uuid,
            "updated_at": datetime.now(UTC).isoformat(),
            **properties,
        }
        await self._neo4j_client.execute_query(query, **params)

    async def extract_entities(
        self,
        content: str,
        project_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        excluded_entity_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract entities from arbitrary memory content without writing the graph."""
        schema_context = await self._load_schema_context(project_id)
        entities = await self._get_entity_extractor().extract(
            content=content,
            entity_types_context=schema_context["entity_types_context"],
            entity_type_id_to_name=schema_context["entity_type_id_to_name"],
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if excluded_entity_types:
            excluded_set = set(excluded_entity_types)
            entities = [entity for entity in entities if entity.entity_type not in excluded_set]

        return [self._entity_to_api_dict(entity) for entity in entities]

    async def extract_relationships(
        self,
        content: str,
        entities: list[dict[str, Any]] | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract relationships from memory content without writing the graph."""
        schema_context = await self._load_schema_context(project_id)
        entity_nodes = self._coerce_entity_nodes(
            entities or [],
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not entity_nodes:
            extracted_entities = await self._get_entity_extractor().extract(
                content=content,
                entity_types_context=schema_context["entity_types_context"],
                entity_type_id_to_name=schema_context["entity_type_id_to_name"],
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            entity_nodes = extracted_entities

        relationships = await self._get_relationship_extractor().extract_from_entity_nodes(
            content=content,
            entity_nodes=entity_nodes,
            edge_type_map=schema_context["edge_type_map"] or None,
        )
        name_by_uuid = {entity.uuid: entity.name for entity in entity_nodes}
        return [
            self._relationship_to_api_dict(relationship, name_by_uuid)
            for relationship in relationships
        ]

    @staticmethod
    def _entity_to_api_dict(entity: EntityNode) -> dict[str, Any]:
        return {
            "uuid": entity.uuid,
            "name": entity.name,
            "type": entity.entity_type,
            "entity_type": entity.entity_type,
            "summary": entity.summary,
            "description": entity.summary,
            "attributes": entity.attributes,
        }

    @staticmethod
    def _relationship_to_api_dict(
        relationship: EntityEdge,
        name_by_uuid: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        name_by_uuid = name_by_uuid or {}
        return {
            "uuid": relationship.uuid,
            "source_uuid": relationship.source_uuid,
            "target_uuid": relationship.target_uuid,
            "source": name_by_uuid.get(relationship.source_uuid, relationship.source_uuid),
            "target": name_by_uuid.get(relationship.target_uuid, relationship.target_uuid),
            "type": relationship.relationship_type,
            "relationship_type": relationship.relationship_type,
            "fact": relationship.fact,
            "summary": relationship.summary,
            "weight": relationship.weight,
            "episodes": relationship.episodes,
        }

    @staticmethod
    def _coerce_entity_nodes(
        entities: list[dict[str, Any]],
        *,
        project_id: str | None,
        tenant_id: str | None,
        user_id: str | None,
    ) -> list[EntityNode]:
        """Convert API entity dictionaries into EntityNode inputs for extraction."""
        entity_nodes: list[EntityNode] = []
        for entity in entities:
            name = entity.get("name")
            if not isinstance(name, str) or not name:
                continue
            entity_type = entity.get("entity_type") or entity.get("type") or "Entity"
            summary = entity.get("summary") or entity.get("description") or ""
            attributes = entity.get("attributes") or {}
            entity_nodes.append(
                EntityNode(
                    uuid=str(entity.get("uuid") or entity.get("id") or uuid4()),
                    name=name,
                    entity_type=str(entity_type),
                    summary=str(summary),
                    attributes=attributes if isinstance(attributes, dict) else {},
                    project_id=project_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            )
        return entity_nodes

    async def _save_discovered_types(
        self,
        project_id: str,
        entities: list[EntityNode],
        relationships: list[EntityEdge],
        existing_entity_types: set[str],
    ) -> None:
        """
        Save discovered entity types and edge types to PostgreSQL.

        This ensures all types used in the knowledge graph are persisted
        for future reference and schema management.

        Args:
            project_id: Project ID
            entities: List of extracted entities
            relationships: List of extracted relationships
            existing_entity_types: Set of entity type names already in schema
        """
        from src.infrastructure.adapters.secondary.schema.dynamic_schema import (
            save_discovered_types_batch,
        )

        # Collect unique entity types not in existing schema
        new_entity_types = []
        seen_entity_types = set(existing_entity_types)

        for entity in entities:
            entity_type = entity.entity_type
            if entity_type and entity_type not in seen_entity_types:
                new_entity_types.append(
                    {
                        "name": entity_type,
                        "description": f"Auto-discovered {entity_type} entity type.",
                    }
                )
                seen_entity_types.add(entity_type)

        # Collect unique edge types
        new_edge_types = set()
        for rel in relationships:
            edge_type = rel.relationship_type
            if edge_type and edge_type not in ("MENTIONS", "BELONGS_TO"):
                new_edge_types.add(edge_type)

        # Collect edge type mappings (source_type, target_type, edge_type)
        new_edge_type_maps = []
        seen_maps = set()

        # Build entity UUID to type mapping
        entity_type_map = {e.uuid: e.entity_type for e in entities}

        for rel in relationships:
            edge_type = rel.relationship_type
            if edge_type in ("MENTIONS", "BELONGS_TO"):
                continue

            source_type = entity_type_map.get(rel.source_uuid, "Entity")
            target_type = entity_type_map.get(rel.target_uuid, "Entity")

            map_key = (source_type, target_type, edge_type)
            if map_key not in seen_maps:
                new_edge_type_maps.append(
                    {
                        "source_type": source_type,
                        "target_type": target_type,
                        "edge_type": edge_type,
                    }
                )
                seen_maps.add(map_key)

        # Save to database if there are new types
        if new_entity_types or new_edge_types or new_edge_type_maps:
            try:
                result = await save_discovered_types_batch(
                    project_id=project_id,
                    entity_types=new_entity_types,
                    edge_types=list(new_edge_types),
                    edge_type_maps=new_edge_type_maps,
                )
                logger.info(
                    f"Saved discovered types for project {project_id}: "
                    f"{result['entity_types_created']} entity types, "
                    f"{result['edge_types_created']} edge types, "
                    f"{result['edge_type_maps_created']} edge type maps"
                )
            except Exception as e:
                # Log but don't fail the episode processing
                logger.warning(
                    "Failed to save discovered types: error_type=%s",
                    type(e).__name__,
                )

    async def _get_existing_entities(
        self, project_id: str | None = None, limit: int = 10000
    ) -> list[EntityNode]:
        """Get existing entities from Neo4j for deduplication.

        Args:
            project_id: Optional project ID to filter entities
            limit: Maximum number of entities to retrieve (default: 10000)
        """
        query = """
            MATCH (e:Entity)
            WHERE $project_id IS NULL OR e.project_id = $project_id
            RETURN e
            ORDER BY e.created_at DESC
            LIMIT $limit
        """
        try:
            result = await self._neo4j_client.execute_query(
                query, project_id=project_id, limit=limit
            )
            entities = []
            for r in result.records:
                node_data = dict(r["e"])
                # Convert Neo4j node dict to EntityNode object
                try:
                    # Parse created_at if it's a string
                    created_at = node_data.get("created_at")
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    else:
                        created_at = datetime.now()

                    # Parse attributes if it's a JSON string
                    attributes = node_data.get("attributes", {})
                    if isinstance(attributes, str):
                        import json

                        attributes = json.loads(attributes) if attributes else {}

                    entity = EntityNode(
                        uuid=node_data.get("uuid", ""),
                        name=node_data.get("name", ""),
                        entity_type=node_data.get("entity_type", "Entity"),
                        labels=node_data.get("labels", []),
                        summary=node_data.get("summary", ""),
                        name_embedding=node_data.get("name_embedding"),
                        embedding_dim=node_data.get("embedding_dim"),
                        attributes=attributes,
                        created_at=created_at,
                        tenant_id=node_data.get("tenant_id"),
                        project_id=node_data.get("project_id"),
                        user_id=node_data.get("user_id"),
                    )
                    entities.append(entity)
                except Exception as e:
                    logger.warning(
                        "Failed to parse entity node: error_type=%s",
                        type(e).__name__,
                    )
                    continue
            return entities
        except Exception as e:
            logger.warning(
                "Failed to get existing entities: error_type=%s",
                type(e).__name__,
            )
            return []

    async def _update_episode_status(
        self,
        episode_uuid: str,
        status: EpisodeStatus,
        entity_edges: list[str] | None = None,
    ) -> None:
        """Update episode status in Neo4j."""
        query = """
            MATCH (e:Episodic {uuid: $uuid})
            SET e.status = $status
        """
        params: dict[str, Any] = {"uuid": episode_uuid, "status": status.value}

        if entity_edges is not None:
            query += ", e.entity_edges = $entity_edges"
            params["entity_edges"] = entity_edges

        await self._neo4j_client.execute_query(query, **params)

    @override
    async def search(self, query: str, project_id: str | None = None, limit: int = 10) -> list[Any]:
        """
        Search the knowledge graph.

        Uses hybrid search combining vector and keyword search.

        Args:
            query: Search query string
            project_id: Optional project ID to filter results
            limit: Maximum number of results

        Returns:
            List of search results (episodes and entities)
        """
        try:
            # Check embedding dimension
            await self._check_embedding_dimension()

            hybrid_search = self._get_hybrid_search()
            result = await hybrid_search.search(
                query=query,
                project_id=project_id,
                limit=limit,
            )

            # Convert to list format expected by callers
            items = []
            for item in result.items:
                if item.type == "episode":
                    items.append(
                        {
                            "type": "episode",
                            "content": item.content,
                            "uuid": item.uuid,
                            "memory_id": item.metadata.get("memory_id", ""),
                        }
                    )
                else:
                    items.append(
                        {
                            "type": "entity",
                            "name": item.name,
                            "summary": item.summary or "",
                            "uuid": item.uuid,
                        }
                    )

            return items[:limit]

        except Exception as e:
            logger.error("Search failed: error_type=%s", type(e).__name__)
            raise

    @override
    async def get_graph_data(self, project_id: str, limit: int = 100) -> dict[str, Any]:
        """
        Retrieve graph data (nodes and edges) for visualization.

        Args:
            project_id: Project ID to get graph data for
            limit: Maximum number of nodes to return

        Returns:
            Dictionary with 'nodes' and 'edges' lists
        """
        try:
            # Query to get episodes, entities, and their relationships
            query = """
                MATCH (e:Episodic {project_id: $project_id})
                OPTIONAL MATCH (e)-[r:MENTIONS]->(n:Entity)
                RETURN e, r, n
                LIMIT $limit
            """

            result = await self._neo4j_client.execute_query(
                query, project_id=project_id, limit=limit
            )

            nodes = {}
            edges = []
            seen_nodes = set()

            for record in result.records:
                # Extract episode node
                episode = record.get("e")
                if episode and episode.element_id not in seen_nodes:
                    nodes[episode.element_id] = {
                        "id": episode.element_id,
                        "label": episode.get("name", episode.get("uuid", "")),
                        "type": "episode",
                        "uuid": episode.get("uuid"),
                        "content": episode.get("content", ""),
                        "project_id": episode.get("project_id"),
                        "tenant_id": episode.get("tenant_id"),
                    }
                    seen_nodes.add(episode.element_id)

                # Extract entity node
                entity = record.get("n")
                if entity and entity.element_id not in seen_nodes:
                    nodes[entity.element_id] = {
                        "id": entity.element_id,
                        "label": entity.get("name", entity.get("uuid", "")),
                        "type": "entity",
                        "uuid": entity.get("uuid"),
                        "name": entity.get("name", ""),
                        "summary": entity.get("summary", ""),
                    }
                    seen_nodes.add(entity.element_id)

                # Extract relationship
                relationship = record.get("r")
                if relationship and episode and entity:
                    edges.append(
                        {
                            "id": relationship.element_id,
                            "source": episode.element_id,
                            "target": entity.element_id,
                            "label": relationship.type,
                        }
                    )

            # Also get entity-to-entity relationships
            entity_query = """
                MATCH (e1:Entity {project_id: $project_id})-[r]->(e2:Entity {project_id: $project_id})
                RETURN e1, r, e2
                LIMIT $limit
            """

            entity_result = await self._neo4j_client.execute_query(
                entity_query, project_id=project_id, limit=limit
            )

            for record in entity_result.records:
                e1 = record.get("e1")
                e2 = record.get("e2")
                rel = record.get("r")

                if e1 and e1.element_id not in seen_nodes:
                    nodes[e1.element_id] = {
                        "id": e1.element_id,
                        "label": e1.get("name", ""),
                        "type": "entity",
                        "uuid": e1.get("uuid"),
                        "name": e1.get("name", ""),
                        "summary": e1.get("summary", ""),
                    }
                    seen_nodes.add(e1.element_id)

                if e2 and e2.element_id not in seen_nodes:
                    nodes[e2.element_id] = {
                        "id": e2.element_id,
                        "label": e2.get("name", ""),
                        "type": "entity",
                        "uuid": e2.get("uuid"),
                        "name": e2.get("name", ""),
                        "summary": e2.get("summary", ""),
                    }
                    seen_nodes.add(e2.element_id)

                if rel and e1 and e2:
                    edges.append(
                        {
                            "id": rel.element_id,
                            "source": e1.element_id,
                            "target": e2.element_id,
                            "label": rel.get("relationship_type", rel.type),
                        }
                    )

            return {"nodes": list(nodes.values()), "edges": edges}

        except Exception as e:
            logger.error(
                "Failed to get graph data: error_type=%s",
                type(e).__name__,
            )
            raise

    @override
    async def delete_episode(self, episode_name: str) -> bool:
        """
        Delete an episode by name from the graph.

        Args:
            episode_name: The name of the episode to delete

        Returns:
            True if deletion was successful
        """
        try:
            query = "MATCH (e:Episodic {name: $episode_name}) DETACH DELETE e"
            await self._neo4j_client.execute_query(query, episode_name=episode_name)
            logger.info(f"Successfully deleted episode: {episode_name}")
            return True

        except Exception as e:
            logger.error("Failed to delete episode: error_type=%s", type(e).__name__)
            raise

    @override
    async def delete_episode_by_memory_id(self, memory_id: str) -> bool:
        """
        Delete an episode by memory_id from the graph.

        Args:
            memory_id: The memory_id of the episode to delete

        Returns:
            True if deletion was successful
        """
        return await self.remove_episode_by_memory_id(memory_id)

    async def _cleanup_entity_relationships_for_episodes(
        self,
        episode_match_clause: str,
        params: dict[str, Any],
    ) -> None:
        """Remove or update entity relationships supported by deleted episodes."""
        delete_relationships_query = f"""
            {episode_match_clause}
            MATCH (:Entity)-[r]->(:Entity)
            WHERE r.episodes IS NOT NULL
              AND any(episode_id IN episode_uuids WHERE episode_id IN r.episodes)
            WITH r, episode_uuids,
                 [episode_id IN r.episodes WHERE NOT episode_id IN episode_uuids] AS remaining
            WHERE size(remaining) = 0
            DELETE r
        """
        await self._neo4j_client.execute_query(delete_relationships_query, **params)

        trim_relationships_query = f"""
            {episode_match_clause}
            MATCH (:Entity)-[r]->(:Entity)
            WHERE r.episodes IS NOT NULL
              AND any(episode_id IN episode_uuids WHERE episode_id IN r.episodes)
            WITH r, episode_uuids,
                 [episode_id IN r.episodes WHERE NOT episode_id IN episode_uuids] AS remaining
            WHERE size(remaining) > 0 AND size(remaining) < size(r.episodes)
            SET r.episodes = remaining
        """
        await self._neo4j_client.execute_query(trim_relationships_query, **params)

    @override
    async def remove_episode(self, episode_uuid: str) -> bool:
        """
        Remove an episode and clean up orphaned entities and edges.

        This method performs comprehensive cleanup:
        1. Delete EntityEdges that were only created by this episode
        2. Delete Entity nodes that are only referenced by this episode
        3. Delete MENTIONS relationships from this episode
        4. Delete the Episodic node itself

        Args:
            episode_uuid: The UUID of the episode to remove

        Returns:
            True if removal was successful
        """
        try:
            # Step 1: Delete or trim entity relationships supported by this episode.
            await self._cleanup_entity_relationships_for_episodes(
                "MATCH (ep:Episodic {uuid: $uuid}) WITH collect(ep.uuid) AS episode_uuids",
                params={"uuid": episode_uuid},
            )

            # Step 2: Delete orphaned entity nodes
            delete_orphan_entities_query = """
                MATCH (ep:Episodic {uuid: $uuid})-[:MENTIONS]->(n:Entity)
                WHERE NOT EXISTS {
                    MATCH (other:Episodic)-[:MENTIONS]->(n)
                    WHERE other.uuid <> $uuid
                }
                DETACH DELETE n
            """
            await self._neo4j_client.execute_query(delete_orphan_entities_query, uuid=episode_uuid)

            # Step 3: Delete the episode node
            delete_episode_query = """
                MATCH (ep:Episodic {uuid: $uuid})
                DETACH DELETE ep
            """
            await self._neo4j_client.execute_query(delete_episode_query, uuid=episode_uuid)

            logger.info(f"Successfully removed episode: {episode_uuid}")
            return True

        except Exception as e:
            logger.error("Failed to remove episode: error_type=%s", type(e).__name__)
            raise

    async def remove_episode_by_memory_id(self, memory_id: str) -> bool:
        """
        Remove an episode by memory_id and clean up orphaned entities.

        Args:
            memory_id: The memory_id of the episode to remove

        Returns:
            True if removal was successful
        """
        try:
            # Step 1: Clear entity embeddings (important for LLM provider switches)
            clear_embeddings_query = """
                MATCH (ep:Episodic {memory_id: $memory_id})-[:MENTIONS]->(n:Entity)
                REMOVE n.name_embedding
                RETURN count(n) AS cleared_count
            """
            result = await self._neo4j_client.execute_query(
                clear_embeddings_query, memory_id=memory_id
            )
            cleared_count = result.records[0]["cleared_count"] if result.records else 0
            logger.info(f"Cleared embeddings from {cleared_count} entities for memory {memory_id}")

            # Step 2: Delete or trim entity relationships supported by this memory's episodes.
            await self._cleanup_entity_relationships_for_episodes(
                """
                MATCH (ep:Episodic {memory_id: $memory_id})
                WITH collect(ep.uuid) AS episode_uuids
                """,
                params={"memory_id": memory_id},
            )

            # Step 3: Delete orphan entities
            delete_orphan_entities_query = """
                MATCH (ep:Episodic {memory_id: $memory_id})-[:MENTIONS]->(n:Entity)
                WHERE NOT EXISTS {
                    MATCH (other:Episodic)-[:MENTIONS]->(n)
                    WHERE other.memory_id <> $memory_id
                }
                DETACH DELETE n
            """
            await self._neo4j_client.execute_query(
                delete_orphan_entities_query, memory_id=memory_id
            )

            # Step 4: Delete the episode
            delete_episode_query = """
                MATCH (ep:Episodic {memory_id: $memory_id})
                DETACH DELETE ep
            """
            await self._neo4j_client.execute_query(delete_episode_query, memory_id=memory_id)

            logger.info(f"Successfully removed episode with memory_id: {memory_id}")
            return True

        except Exception as e:
            logger.warning(
                "Failed to remove episode by memory_id: error_type=%s",
                type(e).__name__,
            )
            return False

    async def search_memories(
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
        **_kwargs: Any,  # noqa: ANN401
    ) -> list[dict[str, Any]]:
        """
        Search memories in the knowledge graph.

        This is an alias for the search() method to provide compatibility
        with agent tools that expect this method signature.

        Args:
            query: Search query string
            project_id: Optional project ID to search within
            limit: Maximum number of results

        Returns:
            List of search results as dictionaries
        """
        results = await self.search(query=query, project_id=project_id, limit=limit)
        return results

    # ==================================================================
    # GraphStorePort primitives (Phase 2b)
    #
    # These methods implement the new semantic store primitives by lifting
    # the raw Cypher that previously lived in routers / Neo4jClient into the
    # adapter, returning the typed DTOs from src.domain.model.graph. They let
    # routers drop their raw ``.driver.execute_query`` bypasses entirely.
    # ==================================================================

    async def initialize_schema(self) -> None:
        """Create the standard indices + default vector index for this backend."""
        await self._neo4j_client.build_indices()

    async def vector_search(
        self,
        query_vector: list[float],
        limit: int = 10,
        project_id: str | None = None,
        index_name: str | None = None,
    ) -> list[GraphSearchHit]:
        """Vector similarity search over the default entity index."""
        idx = index_name or "entity_name_vector"
        raw = await self._neo4j_client.vector_search(
            index_name=idx,
            query_vector=query_vector,
            limit=limit,
            project_id=project_id,
        )
        return [GraphSearchHit(node=h["node"], score=float(h["score"])) for h in raw]

    async def fulltext_search(
        self,
        query: str,
        limit: int = 10,
        project_id: str | None = None,
        index_name: str | None = None,
    ) -> list[GraphSearchHit]:
        """Fulltext search over the entity name+summary index by default."""
        idx = index_name or "entity_name_summary"
        raw = await self._neo4j_client.fulltext_search(
            index_name=idx,
            query=query,
            limit=limit,
            project_id=project_id,
        )
        return [GraphSearchHit(node=h["node"], score=float(h["score"])) for h in raw]

    async def related_entities(
        self,
        entity_id: str,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[GraphEntityDTO]:
        """Return entities directly related to ``entity_id`` (any edge type)."""
        scope = ""
        if project_id:
            scope = "WHERE b.project_id = $project_id"
        q = f"""
            MATCH (a:Entity {{uuid: $entity_id}})-[r]-(b:Entity)
            {scope}
            RETURN DISTINCT b
            LIMIT $limit
        """
        params: dict[str, Any] = {"entity_id": entity_id, "limit": limit}
        if project_id:
            params["project_id"] = project_id
        result = await self._neo4j_client.execute_query(q, **params)
        out: list[GraphEntityDTO] = []
        for record in result.records:
            node = record.get("b")
            if node is None:
                continue
            props = dict(node)
            raw_entity_type = props.get("entity_type", props.get("type"))
            entity_type = (
                raw_entity_type
                if isinstance(raw_entity_type, str) and raw_entity_type
                else "Entity"
            )
            out.append(
                GraphEntityDTO(
                    uuid=props.get("uuid", ""),
                    name=props.get("name", ""),
                    entity_type=entity_type,
                    summary=props.get("summary", "") or "",
                    project_id=props.get("project_id"),
                    extra={k: v for k, v in props.items()
                           if k not in {"uuid", "name", "entity_type", "summary", "project_id"}},
                )
            )
        return out

    async def community_read(
        self,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[GraphCommunityDTO]:
        """Read communities, optionally scoped to a project."""
        scope = ""
        params: dict[str, Any] = {"limit": limit}
        if project_id:
            scope = "WHERE c.project_id = $project_id"
            params["project_id"] = project_id
        q = f"""
            MATCH (c:Community)
            {scope}
            RETURN c
            ORDER BY c.member_count DESC
            LIMIT $limit
        """
        result = await self._neo4j_client.execute_query(q, **params)
        out: list[GraphCommunityDTO] = []
        for record in result.records:
            node = record.get("c")
            if node is None:
                continue
            props = dict(node)
            out.append(
                GraphCommunityDTO(
                    uuid=props.get("uuid", ""),
                    name=props.get("name", ""),
                    summary=props.get("summary", "") or "",
                    member_count=int(props.get("member_count", 0) or 0),
                    project_id=props.get("project_id"),
                    extra={k: v for k, v in props.items()
                           if k not in {"uuid", "name", "summary", "member_count", "project_id"}},
                )
            )
        return out

    async def graph_snapshot(self, project_id: str, limit: int = 100) -> GraphGraphDataDTO:
        """Typed nodes/edges snapshot for a project (graph visualization)."""
        data = await self.get_graph_data(project_id, limit=limit)
        nodes = [
            GraphNodeDTO(
                id=str(n.get("id", n.get("uuid", ""))),
                label=str(n.get("label", n.get("name", ""))),
                type=str(n.get("type", "")),
                uuid=n.get("uuid"),
                extra={k: v for k, v in n.items() if k not in {"id", "label", "type", "uuid"}},
            )
            for n in data.get("nodes", [])
        ]
        edges = [
            GraphRelationshipDTO(
                id=str(e.get("id", "")),
                source=str(e.get("source", "")),
                target=str(e.get("target", "")),
                label=str(e.get("label", "")),
                extra={k: v for k, v in e.items() if k not in {"id", "source", "target", "label"}},
            )
            for e in data.get("edges", [])
        ]
        return GraphGraphDataDTO(nodes=nodes, edges=edges)

    def _export_scope(self, var: str, project_id: str | None, tenant_id: str | None) -> str:
        if project_id:
            return f"WHERE {var}.project_id = $project_id"
        if tenant_id:
            return f"WHERE {var}.tenant_id = $tenant_id"
        return ""

    def _export_entity_scope(self, var: str, project_id: str | None, tenant_id: str | None) -> str:
        # Entities may be MENTIONed by episodes of a different project;
        # reproduce the router's MENTION-aware scoping for entities.
        if project_id:
            cond = self._project_node_scope_condition(var)
            return f"WHERE {cond}"
        if tenant_id:
            return f"WHERE {var}.tenant_id = $tenant_id"
        return ""

    async def _export_episodes(self, params: dict[str, Any], scope: str) -> list[dict[str, Any]]:
        q = f"MATCH (e:Episodic) {scope} RETURN properties(e) as props ORDER BY e.created_at DESC"
        res = await self._neo4j_client.execute_query(q, **params)
        return [dict(r["props"]) for r in res.records if r.get("props") is not None]

    async def _export_entities(self, params: dict[str, Any], scope: str) -> list[dict[str, Any]]:
        q = f"MATCH (e:Entity) {scope} RETURN properties(e) as props, labels(e) as labels"
        res = await self._neo4j_client.execute_query(q, **params)
        out: list[dict[str, Any]] = []
        for r in res.records:
            if r.get("props") is None:
                continue
            props = dict(r["props"])
            props["labels"] = list(r.get("labels", []))
            out.append(props)
        return out

    async def _export_relationships(
        self, params: dict[str, Any], project_id: str | None, tenant_id: str | None
    ) -> list[dict[str, Any]]:
        label_filter = (
            "('Entity' IN labels(a) OR 'Episodic' IN labels(a) OR 'Community' IN labels(a)) "
            "AND ('Entity' IN labels(b) OR 'Episodic' IN labels(b) OR 'Community' IN labels(b))"
        )
        if project_id:
            cond_a = self._project_node_scope_condition("a")
            cond_b = self._project_node_scope_condition("b")
            scope = f"WHERE {label_filter} AND {cond_a} AND {cond_b}"
        elif tenant_id:
            scope = (
                f"WHERE {label_filter} AND a.tenant_id = $tenant_id "
                "AND b.tenant_id = $tenant_id"
            )
        else:
            scope = f"WHERE {label_filter}"
        q = (
            "MATCH (a)-[r]->(b) "
            f"{scope} "
            "RETURN properties(r) as props, type(r) as rel_type, elementId(r) as edge_id"
        )
        res = await self._neo4j_client.execute_query(q, **params)
        return [
            {"edge_id": r["edge_id"], "type": r["rel_type"], "properties": dict(r["props"])}
            for r in res.records
        ]

    async def _export_communities(self, params: dict[str, Any], scope: str) -> list[dict[str, Any]]:
        q = f"MATCH (c:Community) {scope} RETURN properties(c) as props"
        res = await self._neo4j_client.execute_query(q, **params)
        return [dict(r["props"]) for r in res.records if r.get("props") is not None]

    async def data_export(
        self,
        tenant_id: str | None = None,
        project_id: str | None = None,
        include_episodes: bool = True,
        include_entities: bool = True,
        include_relationships: bool = True,
        include_communities: bool = True,
    ) -> GraphExportDTO:
        """Export graph data as a typed envelope.

        Mirrors the previous ``data_export`` router Cypher while keeping the
        frozen envelope shape (exported_at/tenant_id/project_id + four lists).
        Scope is project-first, then tenant.
        """
        params: dict[str, Any] = {"tenant_id": tenant_id, "project_id": project_id}

        episodes = (
            await self._export_episodes(params, self._export_scope("e", project_id, tenant_id))
            if include_episodes
            else []
        )
        entities = (
            await self._export_entities(
                params, self._export_entity_scope("e", project_id, tenant_id)
            )
            if include_entities
            else []
        )
        relationships = (
            await self._export_relationships(params, project_id, tenant_id)
            if include_relationships
            else []
        )
        communities = (
            await self._export_communities(
                params, self._export_scope("c", project_id, tenant_id)
            )
            if include_communities
            else []
        )

        return GraphExportDTO(
            exported_at=datetime.now(UTC).isoformat(),
            tenant_id=tenant_id,
            project_id=project_id,
            episodes=episodes,
            entities=entities,
            relationships=relationships,
            communities=communities,
        )

    async def count_nodes(
        self,
        project_id: str | None = None,
        tenant_id: str | None = None,
        label: str | None = None,
    ) -> int:
        """Count nodes, optionally filtered by label and project/tenant scope."""
        # label is structural (a Cypher identifier); validate it to stay safe.
        if label:
            _validate_identifier(label)
        label_clause = f":{label}" if label else ""
        scope = ""
        if project_id:
            scope = "WHERE n.project_id = $project_id"
        elif tenant_id:
            scope = "WHERE n.tenant_id = $tenant_id"
        q = f"MATCH (n{label_clause}) {scope} RETURN count(n) AS total"
        params: dict[str, Any] = {}
        if project_id:
            params["project_id"] = project_id
        elif tenant_id:
            params["tenant_id"] = tenant_id
        result = await self._neo4j_client.execute_query(q, **params)
        if result.records:
            return int(result.records[0].get("total", 0) or 0)
        return 0

    async def delete_entity(self, entity_id: str, project_id: str | None = None) -> bool:
        """Delete an entity node by uuid within the project scope."""
        scope = "AND e.project_id = $project_id" if project_id else ""
        q = f"MATCH (e:Entity {{uuid: $entity_id}}) {scope} DETACH DELETE e"
        params: dict[str, Any] = {"entity_id": entity_id}
        if project_id:
            params["project_id"] = project_id
        await self._neo4j_client.execute_query(q, **params)
        return True

    async def delete_project(self, project_id: str) -> int:
        """Delete all graph data for a project; return the number of nodes removed."""
        q = """
            MATCH (n {project_id: $project_id})
            WITH n LIMIT 10000
            DETACH DELETE n
            RETURN count(n) AS deleted
        """
        result = await self._neo4j_client.execute_query(q, project_id=project_id)
        if result.records:
            return int(result.records[0].get("deleted", 0) or 0)
        return 0

    @staticmethod
    def _project_node_scope_condition(var: str) -> str:
        """Cypher predicate matching nodes belonging to a project.

        A node belongs to the project if it has that ``project_id`` OR it is
        MENTIONed by an Episodic node of that project (entities can be shared).
        Reproduces ``data_export._project_node_scope_condition``.
        """
        return (
            f"({var}.project_id = $project_id OR EXISTS {{ "
            f"MATCH ({var})<-[:MENTIONS]-(project_episode:Episodic) "
            "WHERE project_episode.project_id = $project_id })"
        )

    async def count_stats(
        self,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, int]:
        """Return per-type node + relationship counts (mirrors the /stats route)."""
        params: dict[str, Any] = {"tenant_id": tenant_id, "project_id": project_id}

        def _node_scope(var: str) -> str:
            if project_id:
                return f"WHERE {var}.project_id = $project_id"
            if tenant_id:
                return f"WHERE {var}.tenant_id = $tenant_id"
            return ""

        async def _count(label: str, scope_fn: Any) -> int:  # noqa: ANN401
            sc = scope_fn("e")
            q = f"MATCH (e:{label}) {sc} RETURN count(e) AS count"
            res = await self._neo4j_client.execute_query(q, **params)
            return int(res.records[0].get("count", 0) or 0) if res.records else 0

        def _entity_scope_clause(var: str) -> str:
            if project_id:
                cond = self._project_node_scope_condition(var)
                return f"WHERE {cond}"
            if tenant_id:
                return f"WHERE {var}.tenant_id = $tenant_id"
            return ""

        entity_count = await _count("Entity", _entity_scope_clause)
        episode_count = await _count("Episodic", _node_scope)
        community_count = await _count("Community", _node_scope)

        label_filter = (
            "('Entity' IN labels(a) OR 'Episodic' IN labels(a) OR 'Community' IN labels(a)) "
            "AND ('Entity' IN labels(b) OR 'Episodic' IN labels(b) OR 'Community' IN labels(b))"
        )
        if project_id:
            cond_a = self._project_node_scope_condition("a")
            cond_b = self._project_node_scope_condition("b")
            scope = f"WHERE {label_filter} AND {cond_a} AND {cond_b}"
        elif tenant_id:
            scope = f"WHERE {label_filter} AND a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id"
        else:
            scope = f"WHERE {label_filter}"
        rel_q = f"MATCH (a)-[r]->(b) {scope} RETURN count(r) AS count"
        rel_res = await self._neo4j_client.execute_query(rel_q, **params)
        rel_count = int(rel_res.records[0].get("count", 0) or 0) if rel_res.records else 0

        return {
            "entities": entity_count,
            "episodes": episode_count,
            "communities": community_count,
            "relationships": rel_count,
            "total_nodes": entity_count + episode_count + community_count,
        }

    async def list_episodes(
        self,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_ids: list[str] | None = None,
        user_id: str | None = None,
        sort_by: str = "created_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List episodes with filtering/sorting/pagination.

        Returns {'episodes': [props...], 'total': int}. Mirrors the previous
        ``episodes`` router Cypher exactly (tenant/project/user filters, sort on
        created_at|valid_at|name, SKIP/LIMIT).
        """
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if tenant_id is not None:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id
        if project_id:
            conditions.append("e.project_id = $project_id")
            params["project_id"] = project_id
        elif project_ids is not None:
            conditions.append("e.project_id IN $project_ids")
            params["project_ids"] = project_ids
        if user_id:
            conditions.append("e.user_id = $user_id")
            params["user_id"] = user_id
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        # sort field is structural (validated by caller against allowlist);
        # validate defensively to keep Cypher identifier-safe.
        _validate_identifier(sort_by)
        sort_field = sort_by
        order = "DESC" if sort_desc else "ASC"

        count_q = f"MATCH (e:Episodic) {where_clause} RETURN count(e) AS total"
        count_res = await self._neo4j_client.execute_query(count_q, **params)
        total = int(count_res.records[0].get("total", 0) or 0) if count_res.records else 0

        list_q = (
            f"MATCH (e:Episodic) {where_clause} "
            f"RETURN properties(e) AS props ORDER BY e.{sort_field} {order} "
            "SKIP $offset LIMIT $limit"
        )
        params["offset"] = offset
        params["limit"] = limit
        res = await self._neo4j_client.execute_query(list_q, **params)
        episodes = [dict(r["props"]) for r in res.records if r.get("props") is not None]
        return {"episodes": episodes, "total": total}

    async def get_episode_by_name(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Return a single episode's properties by name, or None if not found."""
        conditions: list[str] = []
        params: dict[str, Any] = {"name": name}
        if tenant_id is not None:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id
        if project_ids is not None:
            conditions.append("e.project_id IN $project_ids")
            params["project_ids"] = project_ids
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        q = f"MATCH (e:Episodic {{name: $name}}) {where_clause} RETURN properties(e) AS props"
        res = await self._neo4j_client.execute_query(q, **params)
        if not res.records:
            return None
        props = res.records[0].get("props")
        return dict(props) if props is not None else None

    async def delete_episode_by_name(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> int:
        """Delete an episode by name (DETACH DELETE); return count deleted (0 if absent)."""
        conditions: list[str] = []
        params: dict[str, Any] = {"name": name}
        if tenant_id is not None:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id
        if project_ids is not None:
            conditions.append("e.project_id IN $project_ids")
            params["project_ids"] = project_ids
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        q = (
            f"MATCH (e:Episodic {{name: $name}}) {where_clause} "
            "DETACH DELETE e RETURN count(e) AS deleted"
        )
        res = await self._neo4j_client.execute_query(q, **params)
        return int(res.records[0].get("deleted", 0) or 0) if res.records else 0

    async def recall_recent_episodes(
        self,
        *,
        since_iso: str,
        limit: int = 100,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return episodes created at/after an ISO datetime, newest first.

        Mirrors the previous ``recall`` router Cypher (time-window + scope filters).
        """
        conditions: list[str] = ["e.created_at >= datetime($since_date)"]
        params: dict[str, Any] = {"since_date": since_iso, "limit": limit}
        if project_id:
            conditions.append("e.project_id = $project_id")
            params["project_id"] = project_id
        elif project_ids is not None:
            conditions.append("e.project_id IN $project_ids")
            params["project_ids"] = project_ids
        if tenant_id:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id
        where_clause = "WHERE " + " AND ".join(conditions)
        q = (
            f"MATCH (e:Episodic) {where_clause} "
            "RETURN properties(e) AS props ORDER BY e.created_at DESC LIMIT $limit"
        )
        res = await self._neo4j_client.execute_query(q, **params)
        return [dict(r["props"]) for r in res.records if r.get("props") is not None]

    async def ensure_episodic_node(
        self,
        *,
        uuid: str,
        name: str,
        content: str,
        source_description: str,
        source: str,
        created_at_iso: str,
        group_id: str | None,
        tenant_id: str | None,
        project_id: str | None,
        user_id: str | None,
        memory_id: str | None,
    ) -> None:
        """Pre-create an Episodic node (MERGE) to avoid write races.

        Reproduces the pre-create MERGE previously inlined in the ``memories``
        router. Used to guarantee an episode node exists before background
        processing begins.
        """
        q = """
            MERGE (e:Episodic {uuid: $uuid})
            SET e:Node,
                e.name = $name,
                e.content = $content,
                e.source_description = $source_description,
                e.source = $source,
                e.created_at = datetime($created_at),
                e.valid_at = datetime($created_at),
                e.group_id = $group_id,
                e.tenant_id = $tenant_id,
                e.project_id = $project_id,
                e.user_id = $user_id,
                e.memory_id = $memory_id,
                e.status = 'Processing',
                e.entity_edges = []
        """
        await self._neo4j_client.execute_query(
            q,
            uuid=uuid,
            name=name,
            content=content,
            source_description=source_description,
            source=source,
            created_at=created_at_iso,
            group_id=group_id,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            memory_id=memory_id,
        )

    async def count_entities_by_project(self, project_ids: list[str]) -> dict[str, int]:
        """Bulk entity counts per project_id. Returns {project_id: count}.

        Reproduces the previous ``projects`` router bulk-count Cypher.
        """
        if not project_ids:
            return {}
        q = (
            "MATCH (n:Entity) WHERE n.project_id IN $project_ids "
            "RETURN n.project_id AS project_id, count(n) AS cnt"
        )
        res = await self._neo4j_client.execute_query(q, project_ids=project_ids)
        out: dict[str, int] = {}
        for record in res.records:
            pid = record.get("project_id")
            if pid is not None:
                out[str(pid)] = int(record.get("cnt", 0) or 0)
        return out

    async def count_active_nodes(
        self,
        project_id: str,
        since_iso: str,
    ) -> int:
        """Count nodes valid at/after an ISO datetime within a project.

        Reproduces the previous ``_query_active_nodes`` helper (7-day activity).
        """
        q = (
            "MATCH (n:Node) WHERE n.project_id = $project_id "
            "AND n.valid_at >= $threshold RETURN count(n) AS active_count"
        )
        try:
            res = await self._neo4j_client.execute_query(
                q, project_id=project_id, threshold=since_iso
            )
            if res.records:
                return int(res.records[0].get("active_count", 0) or 0)
        except Exception as e:
            logger.error("Failed to get active nodes: %s", e)
        return 0

    async def trending_entities(
        self,
        project_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return top entities by relationship count for a project.

        Reproduces the previous ``projects`` router trending-entities Cypher.
        """
        q = """
            MATCH (n:Entity)
            WHERE n.project_id = $project_id
            OPTIONAL MATCH (n)-[r]-()
            WITH n, count(r) as rel_count
            ORDER BY rel_count DESC
            LIMIT $limit
            RETURN n.name as name,
                   coalesce(n.entity_type, 'unknown') as entity_type,
                   rel_count as mention_count,
                   n.summary as summary
        """
        res = await self._neo4j_client.execute_query(q, project_id=project_id, limit=limit)
        return [
            {
                "name": r.get("name", ""),
                "entity_type": r.get("entity_type", "unknown"),
                "mention_count": r.get("mention_count", 0),
                "summary": r.get("summary"),
            }
            for r in res.records
        ]

    def _scope_conditions(
        self,
        var: str,
        project_id: str | None,
        tenant_id: str | None,
        project_ids: list[str] | None,
    ) -> tuple[list[str], dict[str, Any]]:
        """Build project/tenant scope conditions for a Cypher node variable.

        Returns (conditions, params). Mirrors the router-side scoping used by the
        enhanced-search endpoints. project_id wins; otherwise project_ids; tenant
        is additive.
        """
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if project_id:
            conditions.append(f"{var}.project_id = $project_id")
            params["project_id"] = project_id
        elif project_ids is not None:
            conditions.append(f"{var}.project_id IN $project_ids")
            params["project_ids"] = project_ids
        if tenant_id:
            conditions.append(f"{var}.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id
        return conditions, params

    async def get_entity_project_id(self, entity_uuid: str) -> str | None:
        """Return the project_id of an Entity node, or None if absent."""
        res = await self._neo4j_client.execute_query(
            "MATCH (start:Entity {uuid: $uuid}) RETURN properties(start) AS props",
            uuid=entity_uuid,
        )
        if not res.records:
            return None
        props = res.records[0].get("props")
        return props.get("project_id") if props else None

    async def get_community_project_id(self, community_uuid: str) -> str | None:
        """Return the project_id of a Community node, or None if absent."""
        res = await self._neo4j_client.execute_query(
            "MATCH (c:Community {uuid: $uuid}) RETURN properties(c) AS props",
            uuid=community_uuid,
        )
        if not res.records:
            return None
        props = res.records[0].get("props")
        return props.get("project_id") if props else None

    async def graph_traversal_search(
        self,
        *,
        start_entity_uuid: str,
        max_depth: int,
        relationship_types: list[str] | None,
        limit: int,
        project_id: str,
    ) -> list[dict[str, Any]]:
        """Traverse the graph from a starting entity; return related nodes.

        Each result dict carries props + labels so the router can derive a type.
        Reproduces the previous ``graph-traversal`` Cypher.
        """
        q = f"""
        MATCH path = (start:Entity {{uuid: $uuid}})-[*1..{max_depth}]-(related)
        WHERE ('Entity' IN labels(related) OR 'Episodic' IN labels(related)
               OR 'Community' IN labels(related))
        AND related.project_id = $project_id
        AND (
            size($relationship_types) = 0 OR
            all(rel IN relationships(path) WHERE type(rel) IN $relationship_types)
        )
        RETURN DISTINCT related, properties(related) AS props, labels(related) AS labels
        LIMIT $limit
        """
        res = await self._neo4j_client.execute_query(
            q,
            uuid=start_entity_uuid,
            project_id=project_id,
            relationship_types=relationship_types or [],
            limit=limit,
        )
        return [
            {"props": dict(r["props"]) if r.get("props") else {}, "labels": list(r.get("labels", []))}
            for r in res.records
            if r.get("props") is not None
        ]

    async def community_search(
        self,
        *,
        community_uuid: str,
        project_id: str,
        include_episodes: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return entities (and optionally episodes) within a community.

        Reproduces the previous ``community`` search Cypher.
        """
        items: list[dict[str, Any]] = []
        entity_q = """
            MATCH (c:Community {uuid: $uuid})
            MATCH (e:Entity)-[:BELONGS_TO]->(c)
            WHERE e.project_id = $project_id
            RETURN properties(e) AS props
        """
        res = await self._neo4j_client.execute_query(
            entity_q, uuid=community_uuid, project_id=project_id
        )
        for r in res.records:
            props = dict(r["props"]) if r.get("props") else {}
            items.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "type": "entity",
                    "summary": props.get("summary", ""),
                    "created_at": props.get("created_at"),
                }
            )

        if include_episodes:
            ep_q = """
                MATCH (c:Community {uuid: $uuid})
                MATCH (e:Entity)-[:BELONGS_TO]->(c)
                MATCH (ep:Episodic)-[:MENTIONS]->(e)
                WHERE ep.project_id = $project_id
                RETURN DISTINCT properties(ep) AS props
                LIMIT $limit
            """
            ep_res = await self._neo4j_client.execute_query(
                ep_q, uuid=community_uuid, project_id=project_id, limit=limit
            )
            for r in ep_res.records:
                props = dict(r["props"]) if r.get("props") else {}
                items.append(
                    {
                        "uuid": props.get("uuid", ""),
                        "name": props.get("name", ""),
                        "type": "episode",
                        "content": props.get("content", ""),
                        "created_at": props.get("created_at"),
                    }
                )
        return items[:limit]

    async def temporal_search(
        self,
        *,
        query: str | None,
        since_iso: str | None,
        until_iso: str | None,
        limit: int,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search Episodic nodes within a time window + scope.

        Reproduces the previous ``temporal`` search Cypher. Returns episode dicts.
        """
        conditions, params = self._scope_conditions("e", project_id, tenant_id, project_ids)
        params["limit"] = limit
        if query:
            conditions.append(
                "(toLower(coalesce(e.content, '') + ' ' + coalesce(e.name, '') "
                "+ ' ' + coalesce(e.summary, '')) CONTAINS toLower($query))"
            )
            params["query"] = query
        if since_iso:
            conditions.append("e.created_at >= datetime($since)")
            params["since"] = since_iso
        if until_iso:
            conditions.append("e.created_at <= datetime($until)")
            params["until"] = until_iso
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        q = (
            f"MATCH (e:Episodic) {where_clause} "
            "RETURN properties(e) AS props ORDER BY e.created_at DESC LIMIT $limit"
        )
        res = await self._neo4j_client.execute_query(q, **params)
        out: list[dict[str, Any]] = []
        for r in res.records:
            props = dict(r["props"]) if r.get("props") else {}
            out.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "type": "episode",
                    "content": props.get("content", ""),
                    "created_at": props.get("created_at"),
                }
            )
        return out

    async def faceted_search(
        self,
        *,
        query: str | None,
        entity_types: list[str] | None,
        tags: list[str] | None,
        since_iso: str | None,
        limit: int,
        offset: int,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search Entity nodes with faceted filters + scope.

        Reproduces the previous ``faceted`` search Cypher. Returns entity dicts
        (uuid/name/entity_type/summary/created_at + labels for type derivation).
        """
        conditions, params = self._scope_conditions("e", project_id, tenant_id, project_ids)
        params["limit"] = limit
        params["offset"] = offset
        if query:
            conditions.append(
                "(toLower(coalesce(e.name, '') + ' ' + coalesce(e.summary, '') "
                "+ ' ' + coalesce(e.entity_type, '')) CONTAINS toLower($query))"
            )
            params["query"] = query
        if entity_types:
            conditions.append("e.entity_type IN $entity_types")
            params["entity_types"] = entity_types
        if tags:
            conditions.append("any(tag IN $tags WHERE tag IN coalesce(e.tags, []))")
            params["tags"] = tags
        if since_iso:
            conditions.append("e.created_at >= datetime($since)")
            params["since"] = since_iso
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        q = (
            f"MATCH (e:Entity) {where_clause} "
            "RETURN properties(e) AS props, labels(e) AS labels "
            "SKIP $offset LIMIT $limit"
        )
        res = await self._neo4j_client.execute_query(q, **params)
        out: list[dict[str, Any]] = []
        for r in res.records:
            props = dict(r["props"]) if r.get("props") else {}
            labels = list(r.get("labels", []))
            out.append({**props, "labels": labels})
        return out

    # ------------------------------------------------------------------
    # graph.py router primitives (list/detail/visualization)
    # ------------------------------------------------------------------

    @staticmethod
    def _mention_scope_clause(
        var: str,
        project_id: str | None,
        project_ids: list[str] | None,
    ) -> str:
        """Entity scoping that also matches entities MENTIONed by project episodes."""
        if project_id:
            return (
                f"({var}.project_id = $project_id OR EXISTS {{ "
                f"MATCH ({var})<-[:MENTIONS]-(ep:Episodic) "
                "WHERE ep.project_id = $project_id })"
            )
        if project_ids is not None:
            return (
                f"({var}.project_id IN $project_ids OR EXISTS {{ "
                f"MATCH ({var})<-[:MENTIONS]-(ep:Episodic) "
                "WHERE ep.project_id IN $project_ids })"
            )
        return ""

    async def list_entities(
        self,
        *,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """List entities with filters + pagination; return {'entities', 'total'}.

        Each entity dict carries uuid/name/entity_type/summary/tenant_id/
        project_id/created_at. Reproduces the ``graph`` router list Cypher.
        """
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        mention_clause = self._mention_scope_clause("e", project_id, project_ids)
        if mention_clause:
            conditions.append(mention_clause)
            if project_id:
                params["project_id"] = project_id
            elif project_ids is not None:
                params["project_ids"] = project_ids
        elif tenant_id and is_superuser:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id
        if entity_type:
            conditions.append("(e.entity_type = $entity_type OR $entity_type IN labels(e))")
            params["entity_type"] = entity_type
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        count_q = f"MATCH (e:Entity) {where_clause} RETURN count(e) AS total"
        count_res = await self._neo4j_client.execute_query(count_q, **params)
        total = int(count_res.records[0].get("total", 0) or 0) if count_res.records else 0

        list_q = (
            f"MATCH (e:Entity) {where_clause} "
            "RETURN properties(e) AS props, labels(e) AS labels "
            "ORDER BY e.created_at DESC SKIP $offset LIMIT $limit"
        )
        res = await self._neo4j_client.execute_query(list_q, **params)
        entities = []
        for r in res.records:
            props = dict(r["props"]) if r.get("props") else {}
            entities.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "entity_type": props.get("entity_type", "Entity"),
                    "summary": props.get("summary", ""),
                    "tenant_id": props.get("tenant_id"),
                    "project_id": props.get("project_id"),
                    "created_at": props.get("created_at"),
                }
            )
        return {"entities": entities, "total": total}

    async def list_communities(
        self,
        *,
        min_members: int | None = None,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """List communities with filters + pagination; return {'communities', 'total'}.

        Reproduces the ``graph`` router list-communities Cypher.
        """
        conditions: list[str] = ["coalesce(c.member_count, 0) >= 0"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if project_id:
            conditions.append("c.project_id = $project_id")
            params["project_id"] = project_id
        elif tenant_id and is_superuser:
            conditions.append("c.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id
        elif project_ids is not None:
            conditions.append("c.project_id IN $project_ids")
            params["project_ids"] = project_ids
        if min_members is not None:
            conditions.append("coalesce(c.member_count, 0) >= $min_members")
            params["min_members"] = min_members
        where_clause = "WHERE " + " AND ".join(conditions)

        count_q = f"MATCH (c:Community) {where_clause} RETURN count(c) AS total"
        count_res = await self._neo4j_client.execute_query(count_q, **params)
        total = int(count_res.records[0].get("total", 0) or 0) if count_res.records else 0

        list_q = (
            f"MATCH (c:Community) {where_clause} "
            "RETURN properties(c) AS props "
            "ORDER BY coalesce(c.member_count, 0) DESC SKIP $offset LIMIT $limit"
        )
        res = await self._neo4j_client.execute_query(list_q, **params)
        communities = []
        for r in res.records:
            props = dict(r["props"]) if r.get("props") else {}
            communities.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "summary": props.get("summary", ""),
                    "member_count": props.get("member_count", 0),
                    "tenant_id": props.get("tenant_id"),
                    "project_id": props.get("project_id"),
                    "formed_at": props.get("formed_at"),
                    "created_at": props.get("created_at"),
                }
            )
        return {"communities": communities, "total": total}

    async def get_entity_types(
        self,
        *,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> list[dict[str, Any]]:
        """Return distinct entity types with counts, scoped.

        Reproduces the ``graph`` router entity-types Cypher.
        """
        conditions: list[str] = []
        params: dict[str, Any] = {}
        mention_clause = self._mention_scope_clause("e", project_id, project_ids)
        if mention_clause:
            conditions.append(mention_clause)
            if project_id:
                params["project_id"] = project_id
            elif project_ids is not None:
                params["project_ids"] = project_ids
        elif tenant_id and is_superuser:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        q = f"""
            MATCH (e:Entity) {where_clause}
            WITH coalesce(
                e.entity_type,
                head([label IN labels(e) WHERE NOT label IN ['Entity', 'Node', 'BaseEntity']]),
                'Entity'
            ) AS entity_type, count(e) AS entity_count
            RETURN entity_type, entity_count
            ORDER BY entity_count DESC
        """
        res = await self._neo4j_client.execute_query(q, **params)
        return [
            {"entity_type": r["entity_type"], "count": r["entity_count"]}
            for r in res.records
        ]

    async def get_entity(self, entity_uuid: str) -> dict[str, Any] | None:
        """Return an entity's props + labels by uuid, or None if absent."""
        res = await self._neo4j_client.execute_query(
            "MATCH (e:Entity {uuid: $uuid}) RETURN properties(e) AS props, labels(e) AS labels",
            uuid=entity_uuid,
        )
        if not res.records:
            return None
        props = dict(res.records[0]["props"]) if res.records[0].get("props") else {}
        props["labels"] = list(res.records[0].get("labels", []))
        return props

    async def get_community(self, community_uuid: str) -> dict[str, Any] | None:
        """Return a community's props by uuid, or None if absent."""
        res = await self._neo4j_client.execute_query(
            "MATCH (c:Community {uuid: $uuid}) RETURN properties(c) AS props",
            uuid=community_uuid,
        )
        if not res.records:
            return None
        props = res.records[0].get("props")
        return dict(props) if props is not None else {}

    async def get_entity_relationships(
        self,
        entity_uuid: str,
        *,
        relationship_type: str | None = None,
        limit: int = 50,
        project_id: str | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """Return relationships (out+in) for an entity; {'relationships', 'total'}.

        Reproduces the ``graph`` router entity-relationships Cypher.
        """
        params: dict[str, Any] = {
            "uuid": entity_uuid,
            "limit": limit,
            "project_id": project_id,
            "is_superuser": is_superuser,
        }
        rel_filter = ""
        if relationship_type:
            rel_filter = "AND type(r) = $relationship_type"
            params["relationship_type"] = relationship_type

        count_q = f"""
            MATCH (e:Entity {{uuid: $uuid}})
            MATCH (e)-[r]-(related:Entity)
            WHERE related IS NOT NULL {rel_filter}
            AND ($is_superuser OR related.project_id = $project_id)
            RETURN count(r) AS total
        """
        count_res = await self._neo4j_client.execute_query(count_q, **params)
        total = int(count_res.records[0].get("total", 0) or 0) if count_res.records else 0

        q = f"""
            MATCH (e:Entity {{uuid: $uuid}})
            OPTIONAL MATCH (e)-[r]-(related:Entity)
            WHERE related IS NOT NULL {rel_filter}
            AND ($is_superuser OR related.project_id = $project_id)
            RETURN
                elementId(r) AS edge_id,
                type(r) AS relation_type,
                properties(r) AS edge_props,
                startNode(r) AS start_node,
                endNode(r) AS end_node,
                properties(related) AS related_props,
                labels(related) AS related_labels,
                CASE
                    WHEN startNode(r).uuid = $uuid THEN 'outgoing'
                    ELSE 'incoming'
                END AS direction
            LIMIT $limit
        """
        res = await self._neo4j_client.execute_query(q, **params)
        relationships = []
        for r in res.records:
            edge_props = dict(r["edge_props"] or {})
            related_props = dict(r["related_props"] or {})
            related_labels = list(r.get("related_labels", []))
            # drop embeddings
            edge_props.pop("fact_embedding", None)
            relationships.append(
                {
                    "edge_id": r["edge_id"],
                    "relation_type": r["relation_type"],
                    "direction": r["direction"],
                    "fact": edge_props.get("fact", ""),
                    "score": edge_props.get("score", 0.0),
                    "created_at": edge_props.get("created_at"),
                    "updated_at": edge_props.get("updated_at"),
                    "related_props": related_props,
                    "related_labels": related_labels,
                }
            )
        return {"relationships": relationships, "total": total}

    async def get_community_members(
        self,
        community_uuid: str,
        *,
        limit: int = 100,
        project_id: str | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """Return member entities of a community; {'members', 'total'}."""
        count_q = """
            MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {uuid: $uuid})
            WHERE $is_superuser OR e.project_id = $project_id
            RETURN count(e) AS total
        """
        count_res = await self._neo4j_client.execute_query(
            count_q, uuid=community_uuid, project_id=project_id, is_superuser=is_superuser
        )
        total = int(count_res.records[0].get("total", 0) or 0) if count_res.records else 0

        q = """
            MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {uuid: $uuid})
            WHERE $is_superuser OR e.project_id = $project_id
            RETURN properties(e) AS props
            LIMIT $limit
        """
        res = await self._neo4j_client.execute_query(
            q, uuid=community_uuid, project_id=project_id, is_superuser=is_superuser, limit=limit
        )
        members = []
        for r in res.records:
            props = dict(r["props"]) if r.get("props") else {}
            members.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "entity_type": props.get("entity_type", "Entity"),
                    "summary": props.get("summary", ""),
                    "created_at": props.get("created_at"),
                }
            )
        return {"members": members, "total": total}

    async def get_graph_visualization(
        self,
        *,
        limit: int = 100,
        since: str | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> list[dict[str, Any]]:
        """Return graph elements (nodes/edges) for visualization.

        Returns raw rows (source/target/edge props+labels) so the router can
        assemble the cytoscape-style {'elements': {'nodes', 'edges'}} payload.
        Reproduces the ``graph`` router get-graph Cypher.
        """
        node_where, target_where, scope_params = self._visualization_scope(
            tenant_id, project_id, is_superuser, project_ids
        )
        params: dict[str, Any] = {"limit": limit, "since": since, **scope_params}
        q = f"""
            MATCH (n) {node_where}
            OPTIONAL MATCH (n)-[r]->(m) {target_where}
            WITH n, r, m
            WHERE $since IS NULL
                OR coalesce(toString(n.updated_at), toString(n.created_at), "") >= $since
                OR (m IS NOT NULL
                    AND coalesce(toString(m.updated_at), toString(m.created_at), "") >= $since)
                OR (r IS NOT NULL
                    AND coalesce(toString(r.updated_at), toString(r.created_at), "") >= $since)
            RETURN
                elementId(n) AS source_id, labels(n) AS source_labels, properties(n) AS source_props,
                elementId(r) AS edge_id, type(r) AS edge_type, properties(r) AS edge_props,
                elementId(m) AS target_id, labels(m) AS target_labels, properties(m) AS target_props
            LIMIT $limit
        """
        res = await self._neo4j_client.execute_query(q, **params)
        return [dict(r) for r in res.records]

    async def get_subgraph(
        self,
        *,
        node_uuids: list[str],
        include_neighbors: bool,
        limit: int,
        project_id: str | None,
        tenant_id: str | None,
        project_ids: list[str] | None,
        is_superuser: bool,
    ) -> list[dict[str, Any]]:
        """Return subgraph rows for the given node uuids.

        Reproduces the ``graph`` router subgraph Cypher. Each row carries
        source/target/edge props+labels for the router to assemble elements.
        """
        query = """
            MATCH (n)
            WHERE n.uuid IN $node_uuids
            AND (
                ($project_id IS NOT NULL AND n.project_id = $project_id) OR
                ($project_id IS NULL AND $is_superuser
                    AND ($tenant_id IS NULL OR n.tenant_id = $tenant_id)) OR
                ($project_id IS NULL AND NOT $is_superuser AND n.project_id IN $project_ids)
            )
            WITH n
        """
        if include_neighbors:
            query += """
                OPTIONAL MATCH (n)-[r]-(m)
                WHERE ('Entity' IN labels(m) OR 'Episodic' IN labels(m) OR 'Community' IN labels(m))
                AND (
                    ($project_id IS NOT NULL AND m.project_id = $project_id) OR
                    ($project_id IS NULL AND $is_superuser
                        AND ($tenant_id IS NULL OR m.tenant_id = $tenant_id)) OR
                    ($project_id IS NULL AND NOT $is_superuser AND m.project_id IN $project_ids)
                )
                RETURN
                    elementId(n) AS source_id, labels(n) AS source_labels, properties(n) AS source_props,
                    elementId(r) AS edge_id, type(r) AS edge_type, properties(r) AS edge_props,
                    elementId(m) AS target_id, labels(m) AS target_labels, properties(m) AS target_props
                LIMIT $limit
            """
        else:
            query += """
                RETURN
                    elementId(n) AS source_id, labels(n) AS source_labels, properties(n) AS source_props,
                    null AS edge_id, null AS edge_type, null AS edge_props,
                    null AS target_id, null AS target_labels, null AS target_props
                LIMIT $limit
            """
        res = await self._neo4j_client.execute_query(
            query,
            node_uuids=node_uuids,
            project_id=project_id,
            project_ids=project_ids,
            tenant_id=tenant_id,
            is_superuser=is_superuser,
            limit=limit,
        )
        return [dict(r) for r in res.records]

    def _visualization_scope(
        self,
        tenant_id: str | None,
        project_id: str | None,
        is_superuser: bool,
        project_ids: list[str] | None,
    ) -> tuple[str, str, dict[str, Any]]:
        """Build node/target WHERE clauses + params for visualization queries.

        Mirrors the router's ``_graph_visualization_scope`` helper.
        """
        params: dict[str, Any] = {}
        if project_id:
            node_where = "WHERE n.project_id = $project_id"
            target_where = "WHERE m.project_id = $project_id"
            params["project_id"] = project_id
        elif is_superuser and tenant_id:
            node_where = "WHERE n.tenant_id = $tenant_id"
            target_where = "WHERE m.tenant_id = $tenant_id"
            params["tenant_id"] = tenant_id
        elif project_ids is not None:
            node_where = "WHERE n.project_id IN $project_ids"
            target_where = "WHERE m.project_id IN $project_ids"
            params["project_ids"] = project_ids
        else:
            node_where = ""
            target_where = ""
        return node_where, target_where, params

    async def rebuild_communities(self, project_id: str) -> dict[str, Any]:
        """Rebuild communities for a project via the Louvain-based updater.

        Reproduces the synchronous path of the ``graph`` router rebuild endpoint:
        drop existing communities, gather project entities, run the community
        updater. Returns {'communities_count', 'entities_processed'}.
        """
        from src.infrastructure.graph.schemas import EntityNode

        # Remove existing communities for this project.
        await self._neo4j_client.execute_query(
            """
            MATCH (c:Community)
            WHERE c.project_id = $project_id OR c.group_id = $project_id
            DETACH DELETE c
            """,
            project_id=project_id,
        )

        entity_result = await self._neo4j_client.execute_query(
            """
            MATCH (e:Entity)
            WHERE e.project_id = $project_id
            RETURN e.uuid AS uuid, e.name AS name, e.entity_type AS entity_type
            """,
            project_id=project_id,
        )
        entities = [
            EntityNode(
                uuid=record["uuid"],
                name=record["name"],
                entity_type=record.get("entity_type", "unknown"),
                project_id=project_id,
            )
            for record in entity_result.records
        ]

        communities_count = 0
        community_updater = self._get_community_updater()
        communities = await community_updater.update_communities_for_entities(
            entities=entities,
            project_id=project_id,
            regenerate_all=True,
        )
        communities_count = len(communities) if communities else 0
        return {"communities_count": communities_count, "entities_processed": len(entities)}

    # ------------------------------------------------------------------
    # maintenance.py router primitives
    # ------------------------------------------------------------------

    def _maintenance_node_scope(
        self,
        project_id: str | None,
        is_superuser: bool,
        allowed_project_ids: list[str],
    ) -> tuple[str | None, dict[str, Any]]:
        """Build a node project-scope condition + params for maintenance queries."""
        if project_id:
            return "n.project_id = $project_id", {"project_id": project_id}
        if not is_superuser:
            return "n.project_id IN $project_ids", {"project_ids": allowed_project_ids}
        return None, {}

    def _maintenance_edge_scope(
        self,
        project_id: str | None,
        is_superuser: bool,
        allowed_project_ids: list[str],
    ) -> tuple[str | None, dict[str, Any]]:
        """Build an edge (both endpoints) project-scope condition + params."""
        if project_id:
            return (
                "a.project_id = $project_id AND b.project_id = $project_id",
                {"project_id": project_id},
            )
        if not is_superuser:
            return (
                "a.project_id IN $project_ids AND b.project_id IN $project_ids",
                {"project_ids": allowed_project_ids},
            )
        return None, {}

    async def count_scoped_nodes(
        self,
        label: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        """Count nodes of a label within the maintenance project scope."""
        _validate_identifier(label)
        safe_label = label
        cond, params = self._maintenance_node_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        where = f" WHERE {cond}" if cond else ""
        q = f"MATCH (n:{safe_label}){where} RETURN count(n) AS count"
        res = await self._neo4j_client.execute_query(q, **params)
        return int(res.records[0].get("count", 0) or 0) if res.records else 0

    async def count_old_episodes(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        """Count episodes older than a cutoff within the maintenance scope."""
        cond, params = self._maintenance_node_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        conditions = ["e.created_at < datetime($cutoff_date)"]
        if cond:
            conditions.append(cond.replace("n.", "e."))
        params["cutoff_date"] = cutoff_iso
        where = "WHERE " + " AND ".join(conditions)
        q = f"MATCH (e:Episodic) {where} RETURN count(e) AS count"
        res = await self._neo4j_client.execute_query(q, **params)
        return int(res.records[0].get("count", 0) or 0) if res.records else 0

    async def find_duplicate_entities(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Find entity groups sharing an exact name within the scope (dry-run dedup)."""
        cond, params = self._maintenance_node_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        cond = cond.replace("n.", "e.") if cond else None
        where = f"WHERE {cond}" if cond else ""
        q = f"""
            MATCH (e:Entity)
            {where}
            WITH e.name AS name, collect(e) AS entities
            WHERE size(entities) > 1
            RETURN name, entities
            LIMIT 100
        """
        res = await self._neo4j_client.execute_query(q, **params)
        return [
            {
                "name": r["name"],
                "count": len(r["entities"]),
                "uuids": [e.get("uuid", "") for e in r["entities"]],
            }
            for r in res.records
        ]

    async def find_stale_edges(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, int]:
        """Return {rel_type: count} of edges older than a cutoff within scope."""
        cond, params = self._maintenance_edge_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        conditions = ["r.created_at < datetime($cutoff_date)"]
        if cond:
            conditions.append(cond)
        params["cutoff_date"] = cutoff_iso
        where = "WHERE " + " AND ".join(conditions)
        q = f"MATCH (a)-[r]->(b) {where} RETURN type(r) AS rel_type, count(r) AS count"
        res = await self._neo4j_client.execute_query(q, **params)
        out: dict[str, int] = {}
        for r in res.records:
            out[r["rel_type"]] = int(r["count"])
        return out

    async def delete_stale_edges(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        """Delete edges older than a cutoff within scope; return count deleted."""
        cond, params = self._maintenance_edge_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        conditions = ["r.created_at < datetime($cutoff_date)"]
        if cond:
            conditions.append(cond)
        params["cutoff_date"] = cutoff_iso
        where = "WHERE " + " AND ".join(conditions)
        q = f"MATCH (a)-[r]->(b) {where} DELETE r RETURN count(r) AS deleted"
        res = await self._neo4j_client.execute_query(q, **params)
        return int(res.records[0].get("deleted", 0) or 0) if res.records else 0

    async def count_missing_embeddings(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        """Count Entity nodes missing name_embedding within the scope."""
        cond, params = self._maintenance_node_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        conditions = ["n.name_embedding IS NULL"]
        if cond:
            conditions.append(cond)
        where = "WHERE " + " AND ".join(conditions)
        q = f"MATCH (n:Entity) {where} RETURN count(n) AS missing_count"
        res = await self._neo4j_client.execute_query(q, **params)
        return int(res.records[0].get("missing_count", 0) or 0) if res.records else 0

    async def get_existing_embedding_dimension(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int | None:
        """Detect the existing embedding dimension in the database, or None."""
        cond, params = self._maintenance_node_scope(
            project_id, is_superuser, allowed_project_ids or []
        )

        conditions = ["n.embedding_dim IS NOT NULL"]
        if cond:
            conditions.append(cond)
        where = "WHERE " + " AND ".join(conditions)
        q = f"MATCH (n:Entity) {where} WITH n LIMIT 1 RETURN n.embedding_dim AS dim"
        res = await self._neo4j_client.execute_query(q, **params)
        dim = int(res.records[0].get("dim", 0) or 0) if res.records else 0
        if dim:
            return dim

        conditions = ["n.name_embedding IS NOT NULL"]
        if cond:
            conditions.append(cond)
        where = "WHERE " + " AND ".join(conditions)
        q = f"MATCH (n:Entity) {where} WITH n LIMIT 1 RETURN size(n.name_embedding) AS dim"
        res = await self._neo4j_client.execute_query(q, **params)
        dim = int(res.records[0].get("dim", 0) or 0) if res.records else 0
        return dim or None

    async def detect_mixed_dimensions(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Detect mixed embedding dimensions within the scope."""
        cond, params = self._maintenance_node_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        conditions = ["n.name_embedding IS NOT NULL"]
        if cond:
            conditions.append(cond)
        where = "WHERE " + " AND ".join(conditions)
        q = (
            f"MATCH (n:Entity) {where} "
            "WITH coalesce(n.embedding_dim, size(n.name_embedding)) AS dim, "
            "count(n) AS count RETURN dim, count ORDER BY count DESC"
        )
        res = await self._neo4j_client.execute_query(q, **params)
        counts = {str(r["dim"]): int(r["count"]) for r in res.records}
        dimensions = [int(d) for d in counts]
        return {
            "has_mixed_dimensions": len(dimensions) > 1,
            "counts": counts,
            "dimensions": dimensions,
            "total_embeddings": sum(counts.values()),
        }

    async def validate_embeddings(
        self,
        expected_dim: int,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate embeddings (dimension mismatches + zero vectors) in scope."""
        cond, params = self._maintenance_node_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        conditions = ["n.name_embedding IS NOT NULL"]
        if cond:
            conditions.append(cond)
        where = "WHERE " + " AND ".join(conditions)
        params["expected_dim"] = expected_dim
        q = (
            f"MATCH (n:Entity) {where} "
            "WITH n, size(n.name_embedding) AS actual_dim "
            "RETURN count(n) AS total_embeddings, "
            "sum(CASE WHEN actual_dim <> $expected_dim THEN 1 ELSE 0 END) "
            "AS dimension_mismatches, "
            "sum(CASE WHEN all(value IN n.name_embedding WHERE value = 0.0) "
            "THEN 1 ELSE 0 END) AS zero_vectors"
        )
        res = await self._neo4j_client.execute_query(q, **params)
        record = res.records[0] if res.records else {}
        mismatches = int(record.get("dimension_mismatches", 0) or 0)
        zero_vectors = int(record.get("zero_vectors", 0) or 0)
        return {
            "valid": mismatches == 0 and zero_vectors == 0,
            "total_embeddings": int(record.get("total_embeddings", 0) or 0),
            "dimension_mismatches": mismatches,
            "zero_vectors": zero_vectors,
            "expected_dimension": expected_dim,
        }

    async def rebuild_embeddings(
        self,
        embedder: Any,  # noqa: ANN401
        project_id: str,
    ) -> dict[str, int]:
        """Regenerate all entity embeddings for a project using ``embedder``."""
        q = """
            MATCH (n:Entity {project_id: $project_id})
            RETURN n.uuid AS uuid,
                   coalesce(n.name, '') AS name,
                   coalesce(n.summary, '') AS summary
        """
        result = await self._neo4j_client.execute_query(q, project_id=project_id)
        processed = 0
        updated = 0
        failed = 0
        for record in result.records:
            processed += 1
            uuid = record.get("uuid")
            if not uuid:
                failed += 1
                continue
            text = "\n".join(
                part for part in (record.get("name"), record.get("summary")) if part
            )
            try:
                embedding = await _create_embedding_from_embedder(embedder, text)
                await self._neo4j_client.execute_query(
                    """
                    MATCH (n:Entity {uuid: $uuid, project_id: $project_id})
                    SET n.name_embedding = $embedding,
                        n.embedding_dim = $embedding_dim
                    RETURN count(n) AS updated
                    """,
                    uuid=uuid,
                    project_id=project_id,
                    embedding=embedding,
                    embedding_dim=len(embedding),
                )
                updated += 1
            except Exception:
                failed += 1
                logger.exception("Failed to rebuild embedding for entity %s", uuid)
        return {"processed": processed, "updated": updated, "failed": failed}

    async def clear_entity_embeddings(
        self,
        project_id: str | None = None,
    ) -> int:
        """Clear entity embeddings (optionally project-scoped); return count cleared."""
        if project_id:
            q = """
                MATCH (n:Entity {project_id: $project_id})
                WHERE n.name_embedding IS NOT NULL
                REMOVE n.name_embedding, n.embedding_dim
                RETURN count(n) AS cleared
            """
            res = await self._neo4j_client.execute_query(q, project_id=project_id)
        else:
            q = """
                MATCH (n:Entity)
                WHERE n.name_embedding IS NOT NULL
                REMOVE n.name_embedding, n.embedding_dim
                RETURN count(n) AS cleared
            """
            res = await self._neo4j_client.execute_query(q)
        return int(res.records[0].get("cleared", 0) or 0) if res.records else 0

    async def get_vector_index_dimension(self, index_name: str = "entity_name_vector") -> int | None:
        """Return the dimension of an existing vector index, or None if absent."""
        return await self._neo4j_client.get_vector_index_dimension(index_name)

    async def create_vector_index(
        self,
        index_name: str,
        label: str,
        property_name: str,
        dimensions: int,
        similarity_function: str = "cosine",
    ) -> None:
        """Create a vector index (delegates to the Neo4j client)."""
        await self._neo4j_client.create_vector_index(
            index_name=index_name,
            label=label,
            property_name=property_name,
            dimensions=dimensions,
            similarity_function=similarity_function,
        )

    async def get_embedding_dimension_distribution(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> tuple[dict[str, int], int]:
        """Return ({dim: count}, total) of embeddings within the maintenance scope."""
        cond, params = self._maintenance_node_scope(
            project_id, is_superuser, allowed_project_ids or []
        )
        conditions = ["n.name_embedding IS NOT NULL"]
        if cond:
            conditions.append(cond)
        where = "WHERE " + " AND ".join(conditions)
        q = (
            f"MATCH (n:Entity) {where} "
            "RETURN count(n) AS total, n.embedding_dim AS dim "
            "ORDER BY total DESC LIMIT 5"
        )
        res = await self._neo4j_client.execute_query(q, **params)
        distribution: dict[str, int] = {}
        total = 0
        for record in res.records:
            dim = record.get("dim")
            count = int(record.get("total", 0) or 0)
            if dim:
                distribution[str(dim)] = count
            total += count
        return distribution, total

    async def get_memory_graph_context(
        self,
        memory_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Load entities + relationships connected to a memory's episode.

        Returns (entities, relationships) as the dict-shaped records the
        ``memories`` router consumes. Matches the previous inlined Cypher exactly.
        """
        try:
            entity_records, _, _ = await self._neo4j_client.driver.execute_query(
                """
                MATCH (episode:Episodic)
                WHERE episode.memory_id = $memory_id OR episode.uuid = $memory_id
                MATCH (episode)-[:MENTIONS]->(entity:Entity)
                RETURN DISTINCT
                    entity.uuid AS id,
                    entity.name AS name,
                    coalesce(entity.entity_type, 'Entity') AS type,
                    entity.summary AS summary,
                    entity.attributes AS attributes
                ORDER BY name
                """,
                memory_id=memory_id,
            )
            entities = [
                {
                    "id": record["id"],
                    "uuid": record["id"],
                    "name": record["name"] or record["id"],
                    "type": record["type"] or "Entity",
                    "entity_type": record["type"] or "Entity",
                    "summary": record["summary"] or "",
                    "properties": _decode_attributes(record["attributes"]),
                    "confidence": 1.0,
                }
                for record in entity_records
                if record["id"] is not None
            ]

            relationship_records, _, _ = await self._neo4j_client.driver.execute_query(
                """
                MATCH (episode:Episodic)
                WHERE episode.memory_id = $memory_id OR episode.uuid = $memory_id
                MATCH (episode)-[:MENTIONS]->(source:Entity)
                MATCH (episode)-[:MENTIONS]->(target:Entity)
                MATCH (source)-[relationship]->(target)
                WHERE source <> target AND NOT type(relationship) IN ['MENTIONS', 'BELONGS_TO']
                RETURN DISTINCT
                    coalesce(relationship.uuid, elementId(relationship)) AS id,
                    source.uuid AS source_id,
                    target.uuid AS target_id,
                    type(relationship) AS type,
                    relationship.fact AS fact,
                    relationship.summary AS summary,
                    relationship.weight AS weight,
                    relationship.episodes AS episodes
                ORDER BY type
                """,
                memory_id=memory_id,
            )
            relationships = [
                {
                    "id": record["id"],
                    "uuid": record["id"],
                    "source_id": record["source_id"],
                    "target_id": record["target_id"],
                    "source_uuid": record["source_id"],
                    "target_uuid": record["target_id"],
                    "type": record["type"],
                    "relationship_type": record["type"],
                    "properties": {
                        "fact": record["fact"] or "",
                        "summary": record["summary"] or "",
                        "weight": record["weight"],
                        "episodes": record["episodes"] or [],
                    },
                    "confidence": record["weight"] if record["weight"] is not None else 1.0,
                }
                for record in relationship_records
                if record["source_id"] is not None and record["target_id"] is not None
            ]
            return entities, relationships
        except Exception as e:
            logger.warning(
                "Failed to load graph context for memory %s: %s", memory_id, e
            )
            return [], []

    async def count_episodes_by_age(
        self,
        cutoff_iso: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Count episodes older than a cutoff (ISO datetime), scoped by project/tenant."""
        sc = ""
        if project_id:
            sc = "WHERE e.project_id = $project_id AND e.created_at < datetime($cutoff_date)"
        elif tenant_id:
            sc = "WHERE e.tenant_id = $tenant_id AND e.created_at < datetime($cutoff_date)"
        else:
            sc = "WHERE e.created_at < datetime($cutoff_date)"
        q = f"MATCH (e:Episodic) {sc} RETURN count(e) AS count"
        params: dict[str, Any] = {"cutoff_date": cutoff_iso}
        if project_id:
            params["project_id"] = project_id
        elif tenant_id:
            params["tenant_id"] = tenant_id
        res = await self._neo4j_client.execute_query(q, **params)
        return int(res.records[0].get("count", 0) or 0) if res.records else 0

    async def delete_episodes_by_age(
        self,
        cutoff_iso: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Delete episodes older than a cutoff (ISO datetime); return count deleted."""
        sc = ""
        if project_id:
            sc = "WHERE e.project_id = $project_id AND e.created_at < datetime($cutoff_date)"
        elif tenant_id:
            sc = "WHERE e.tenant_id = $tenant_id AND e.created_at < datetime($cutoff_date)"
        else:
            sc = "WHERE e.created_at < datetime($cutoff_date)"
        q = f"MATCH (e:Episodic) {sc} DETACH DELETE e RETURN count(e) AS deleted"
        params: dict[str, Any] = {"cutoff_date": cutoff_iso}
        if project_id:
            params["project_id"] = project_id
        elif tenant_id:
            params["tenant_id"] = tenant_id
        res = await self._neo4j_client.execute_query(q, **params)
        return int(res.records[0].get("deleted", 0) or 0) if res.records else 0

    async def health_probe(self) -> bool:
        """Return True iff the backend responds to a trivial query."""
        try:
            result = await self._neo4j_client.execute_query("RETURN 1 AS ok")
            return bool(result.records) and result.records[0].get("ok", 0) == 1
        except Exception:
            logger.warning("Graph backend health probe failed", exc_info=True)
            return False
