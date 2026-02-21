"""
Native Graph Adapter implementing GraphServicePort without Graphiti dependency.

This adapter provides a self-researched knowledge graph system that:
- Extracts entities and relationships using LLM
- Stores knowledge in Neo4j
- Provides hybrid search (vector + keyword)
- Supports community detection with Louvain algorithm
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.domain.model.memory.episode import Episode
from src.domain.ports.services.graph_service_port import GraphServicePort
from src.domain.ports.services.queue_port import QueuePort

from .community.community_updater import CommunityUpdater
from .community.louvain_detector import LouvainDetector
from .embedding.embedding_service import EmbeddingService
from .extraction.entity_extractor import EntityExtractor
from .extraction.reflexion import ReflexionChecker
from .extraction.relationship_extractor import RelationshipExtractor
from .neo4j_client import Neo4jClient
from .schemas import (
    AddEpisodeResult,
    EntityNode,
    EpisodeStatus,
    EpisodeType,
    EpisodicEdge,
    EpisodicNode,
)
from .search.hybrid_search import HybridSearch

logger = logging.getLogger(__name__)

# Cache TTL for embedding dimension checks (seconds)
EMBEDDING_DIM_CACHE_TTL = 10


class NativeGraphAdapter(GraphServicePort):
    """
    Native graph adapter implementing GraphServicePort.

    This adapter provides a complete knowledge graph system without
    depending on Graphiti, using self-researched implementations for:
    - Entity extraction (LLM-based)
    - Relationship discovery (LLM-based)
    - Hybrid search (vector + keyword + RRF)
    - Community detection (Louvain algorithm)

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
        llm_client: Any,
        embedding_service: EmbeddingService,
        queue_port: Optional[QueuePort] = None,
        enable_reflexion: bool = True,
        reflexion_max_iterations: int = 2,
        auto_clear_embeddings: bool = True,
    ):
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

        # Lazily initialized components
        self._entity_extractor: Optional[EntityExtractor] = None
        self._relationship_extractor: Optional[RelationshipExtractor] = None
        self._reflexion_checker: Optional[ReflexionChecker] = None
        self._hybrid_search: Optional[HybridSearch] = None
        self._louvain_detector: Optional[LouvainDetector] = None
        self._community_updater: Optional[CommunityUpdater] = None

        # Cache for embedding dimension checks
        self._embedding_dim_cache: Dict[str, Any] = {"value": None, "expiry": None}

        # Optional distributed transaction coordinator
        self._transaction_coordinator: Optional[Any] = None

    @property
    def client(self) -> Neo4jClient:
        """Get the Neo4j client (for compatibility with tools expecting graphiti_client)."""
        return self._neo4j_client

    @property
    def driver(self):
        """Get the Neo4j driver (for direct driver access)."""
        return self._neo4j_client.driver

    @property
    def embedder(self) -> EmbeddingService:
        """Get the embedding service (for compatibility)."""
        return self._embedding_service

    @property
    def community_updater(self) -> CommunityUpdater:
        """Get the community updater (lazily initialized)."""
        return self._get_community_updater()

    def set_transaction_coordinator(self, coordinator: Any) -> None:
        """
        Set the distributed transaction coordinator.

        Args:
            coordinator: DistributedTransactionCoordinator instance
        """
        self._transaction_coordinator = coordinator

    def get_transaction_coordinator(self) -> Optional[Any]:
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
        """Get or create hybrid search."""
        if self._hybrid_search is None:
            self._hybrid_search = HybridSearch(
                neo4j_client=self._neo4j_client,
                embedding_service=self._embedding_service,
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
            current_dim = self._embedding_service.embedding_dim

            # Check cache first (unless forced)
            now = datetime.now(timezone.utc)
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
            logger.error(f"Failed to check embedding dimension: {e}", exc_info=True)

    async def _get_existing_embedding_dimension(self) -> Optional[int]:
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
                return result.records[0]["dim"]
        except Exception as e:
            logger.debug(f"Failed to get embedding_dim property: {e}")

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
                return result.records[0]["dim"]
        except Exception as e:
            logger.warning(f"Failed to get existing embedding dimension: {e}")
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
                return result.records[0]["cleared"]
        except Exception as e:
            logger.error(f"Failed to clear embeddings: {e}")
        return 0

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
                created_at=datetime.now(timezone.utc),
                valid_at=episode.valid_at or datetime.now(timezone.utc),
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
                logger.warning(
                    "QueuePort not configured. Episode will not be processed asynchronously."
                )

            return episode

        except Exception as e:
            logger.error(f"Failed to add episode: {e}")
            raise

    async def process_episode(
        self,
        episode_uuid: str,
        content: str,
        project_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        excluded_entity_types: Optional[List[str]] = None,
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
            from src.infrastructure.adapters.secondary.schema.dynamic_schema import (
                get_project_schema_context,
            )

            schema_context = await get_project_schema_context(project_id)
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
                    extracted_entities=entities,
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

            # 4. Deduplicate against existing entities
            unique_entities, dedup_map = await extractor.extract_with_dedup(
                content=content,
                existing_entities=await self._get_existing_entities(project_id),
                entity_types_context=entity_types_context,
                entity_type_id_to_name=entity_type_id_to_name,
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            # Use unique_entities, but also track which entities were duplicates
            # Note: Check for None explicitly, as empty list [] is a valid result (all entities duplicated)
            final_entities = unique_entities if unique_entities is not None else entities

            # 5. Save entities to Neo4j
            entity_edges: List[EpisodicEdge] = []
            for entity in final_entities:
                # Save entity node
                await self._neo4j_client.save_node(
                    labels=entity.get_labels(),
                    uuid=entity.uuid,
                    properties=entity.to_neo4j_properties(),
                )

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
                await self._neo4j_client.save_edge(
                    from_uuid=rel.source_uuid,
                    to_uuid=rel.target_uuid,
                    relationship_type=rel.relationship_type,
                    properties=rel.to_neo4j_properties(),
                )

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
            logger.error(f"Failed to process episode {episode_uuid}: {e}", exc_info=True)
            # Update status to failed
            await self._update_episode_status(episode_uuid, EpisodeStatus.FAILED)
            raise

    async def _save_discovered_types(
        self,
        project_id: str,
        entities: List[EntityNode],
        relationships: List[EpisodicEdge],
        existing_entity_types: set,
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
                logger.warning(f"Failed to save discovered types: {e}")

    async def _get_existing_entities(
        self, project_id: Optional[str] = None, limit: int = 10000
    ) -> List[EntityNode]:
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
                        from datetime import datetime

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
                    logger.warning(f"Failed to parse entity node: {e}")
                    continue
            return entities
        except Exception as e:
            logger.warning(f"Failed to get existing entities: {e}")
            return []

    async def _update_episode_status(
        self,
        episode_uuid: str,
        status: EpisodeStatus,
        entity_edges: Optional[List[str]] = None,
    ) -> None:
        """Update episode status in Neo4j."""
        query = """
            MATCH (e:Episodic {uuid: $uuid})
            SET e.status = $status
        """
        params: Dict[str, Any] = {"uuid": episode_uuid, "status": status.value}

        if entity_edges is not None:
            query += ", e.entity_edges = $entity_edges"
            params["entity_edges"] = entity_edges

        await self._neo4j_client.execute_query(query, **params)

    async def search(
        self, query: str, project_id: Optional[str] = None, limit: int = 10
    ) -> List[Any]:
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
            logger.error(f"Search failed: {e}")
            raise

    async def get_graph_data(self, project_id: str, limit: int = 100) -> Dict[str, Any]:
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
                MATCH (e1:Entity {project_id: $project_id})-[r:RELATES_TO]->(e2:Entity)
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
            logger.error(f"Failed to get graph data for project {project_id}: {e}")
            raise

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
            logger.error(f"Failed to delete episode {episode_name}: {e}")
            raise

    async def delete_episode_by_memory_id(self, memory_id: str) -> bool:
        """
        Delete an episode by memory_id from the graph.

        Args:
            memory_id: The memory_id of the episode to delete

        Returns:
            True if deletion was successful
        """
        try:
            query = "MATCH (e:Episodic {memory_id: $memory_id}) DETACH DELETE e"
            await self._neo4j_client.execute_query(query, memory_id=memory_id)
            return True

        except Exception as e:
            logger.warning(f"Failed to delete episode by memory_id {memory_id}: {e}")
            return False

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
            # Step 1: Delete orphaned entity edges
            delete_orphan_edges_query = """
                MATCH (ep:Episodic {uuid: $uuid})
                WHERE ep.entity_edges IS NOT NULL
                WITH ep, ep.entity_edges AS edge_uuids
                UNWIND edge_uuids AS edge_uuid
                MATCH (e1:Entity)-[r:RELATES_TO {uuid: edge_uuid}]->(e2:Entity)
                WHERE r.episodes IS NOT NULL AND size(r.episodes) = 1 AND r.episodes[0] = $uuid
                DELETE r
            """
            result = await self._neo4j_client.execute_query(
                delete_orphan_edges_query, uuid=episode_uuid
            )
            edges_deleted = result.summary.counters.relationships_deleted
            logger.debug(f"Deleted {edges_deleted} orphan edges for episode {episode_uuid}")

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
            logger.error(f"Failed to remove episode {episode_uuid}: {e}")
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

            # Step 2: Delete orphan edges
            delete_orphan_edges_query = """
                MATCH (ep:Episodic {memory_id: $memory_id})
                WHERE ep.entity_edges IS NOT NULL
                WITH ep, ep.entity_edges AS edge_uuids
                UNWIND edge_uuids AS edge_uuid
                MATCH (e1:Entity)-[r:RELATES_TO {uuid: edge_uuid}]->(e2:Entity)
                WHERE r.episodes IS NOT NULL AND size(r.episodes) = 1 AND r.episodes[0] = ep.uuid
                DELETE r
            """
            await self._neo4j_client.execute_query(delete_orphan_edges_query, memory_id=memory_id)

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
            logger.warning(f"Failed to remove episode by memory_id {memory_id}: {e}")
            return False

    async def search_memories(
        self,
        project_id: str,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search memories in the knowledge graph.

        This is an alias for the search() method to provide compatibility
        with agent tools that expect this method signature.

        Args:
            project_id: Project ID to search within
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of search results as dictionaries
        """
        results = await self.search(query=query, project_id=project_id, limit=limit)
        return results
