"""
Louvain-based community detection for knowledge graph.

This module provides:
- Community detection using Louvain algorithm (via Neo4j GDS or networkx)
- Automatic community boundary detection
- Integration with Neo4j for storing community results
"""

import contextlib
import logging
from typing import Any, cast
from uuid import uuid4

from src.infrastructure.graph.neo4j_client import Neo4jClient
from src.infrastructure.graph.schemas import CommunityNode

logger = logging.getLogger(__name__)


class LouvainDetector:
    """
    Louvain-based community detection for knowledge graph entities.

    Uses Neo4j's Graph Data Science (GDS) library when available,
    falls back to in-memory networkx implementation otherwise.

    Example:
        detector = LouvainDetector(neo4j_client)
        communities = await detector.detect_communities(project_id="proj1")
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        use_gds: bool = True,
        min_community_size: int = 2,
    ) -> None:
        """
        Initialize Louvain detector.

        Args:
            neo4j_client: Neo4j client
            use_gds: Whether to use Neo4j GDS (Graph Data Science) library
            min_community_size: Minimum number of entities for a valid community
        """
        self._neo4j_client = neo4j_client
        self._use_gds = use_gds
        self._min_community_size = min_community_size
        self._gds_available: bool | None = None

    async def detect_communities(
        self,
        project_id: str,
        tenant_id: str | None = None,
    ) -> list[CommunityNode]:
        """
        Detect communities in the knowledge graph for a project.

        Args:
            project_id: Project ID to detect communities for
            tenant_id: Optional tenant ID

        Returns:
            List of CommunityNode objects
        """
        # Check if GDS is available
        if self._use_gds and await self._check_gds_available():
            return await self._detect_with_gds(project_id, tenant_id)
        else:
            return await self._detect_with_networkx(project_id, tenant_id)

    async def _check_gds_available(self) -> bool:
        """Check if Neo4j GDS library is available."""
        if self._gds_available is not None:
            return self._gds_available

        try:
            query = "RETURN gds.version() AS version"
            result = await self._neo4j_client.execute_query(query)
            if result.records:
                logger.info(f"Neo4j GDS available: version {result.records[0]['version']}")
                self._gds_available = True
                return True
        except Exception as exc:
            logger.warning(
                "Failed to check Neo4j GDS availability; treating GDS as unavailable.", exc_info=exc
            )

        logger.info("Neo4j GDS not available, using networkx fallback")
        self._gds_available = False
        return False

    async def _detect_with_gds(
        self,
        project_id: str,
        tenant_id: str | None,
    ) -> list[CommunityNode]:
        """
        Detect communities using Neo4j GDS Louvain algorithm.

        Args:
            project_id: Project ID
            tenant_id: Tenant ID

        Returns:
            List of CommunityNode objects
        """
        graph_name = f"community_graph_{project_id}"

        try:
            # Create projected graph using Cypher projection to include all relationship types
            # This is more flexible than native projection which requires specific relationship types
            # Note: We use string formatting for the inner Cypher strings since GDS cypher projection
            # doesn't support nested parameter passing in the same way as regular Cypher queries.
            # The project_id is validated/sanitized before reaching here.
            node_query = (
                f"MATCH (n:Entity) WHERE n.project_id = '{project_id}' "
                f"RETURN id(n) AS id, n.uuid AS uuid"
            )
            rel_query = (
                f"MATCH (a:Entity)-[r]->(b:Entity) "
                f"WHERE a.project_id = '{project_id}' AND b.project_id = '{project_id}' "
                f"RETURN id(a) AS source, id(b) AS target, coalesce(r.weight, 1.0) AS weight"
            )
            create_query = """
                CALL gds.graph.project.cypher(
                    $graph_name,
                    $node_query,
                    $rel_query
                )
                YIELD graphName, nodeCount, relationshipCount
                RETURN graphName, nodeCount, relationshipCount
            """

            try:
                await self._neo4j_client.execute_query(
                    create_query,
                    graph_name=graph_name,
                    node_query=node_query,
                    rel_query=rel_query,
                )
            except Exception as e:
                if "already exists" in str(e).lower():
                    # Drop and recreate
                    await self._neo4j_client.execute_query(
                        "CALL gds.graph.drop($name, false)",
                        name=graph_name,
                    )
                    await self._neo4j_client.execute_query(
                        create_query,
                        graph_name=graph_name,
                        node_query=node_query,
                        rel_query=rel_query,
                    )
                else:
                    raise

            # Run Louvain
            louvain_query = """
                CALL gds.louvain.stream($graph_name, {
                    relationshipWeightProperty: 'weight'
                })
                YIELD nodeId, communityId
                WITH gds.util.asNode(nodeId) AS node, communityId
                RETURN communityId, collect(node.uuid) AS member_uuids
            """

            result = await self._neo4j_client.execute_query(louvain_query, graph_name=graph_name)

            # Create community nodes
            communities = []
            for record in result.records:
                community_id = record["communityId"]
                member_uuids = record["member_uuids"]

                if len(member_uuids) < self._min_community_size:
                    continue

                community = CommunityNode(
                    uuid=str(uuid4()),
                    name=f"Community_{community_id}",
                    summary="",  # Will be filled by CommunityUpdater
                    member_count=len(member_uuids),
                    project_id=project_id,
                    tenant_id=tenant_id,
                )
                communities.append(community)

            return communities

        finally:
            # Clean up projected graph
            with contextlib.suppress(Exception):
                await self._neo4j_client.execute_query(
                    "CALL gds.graph.drop($name, false)",
                    name=graph_name,
                )

    async def _detect_with_networkx(
        self,
        project_id: str,
        tenant_id: str | None,
    ) -> list[CommunityNode]:
        """
        Detect communities using networkx (in-memory fallback).

        Args:
            project_id: Project ID
            tenant_id: Tenant ID

        Returns:
            List of CommunityNode objects
        """
        try:
            import networkx as nx
            from networkx.algorithms.community import louvain_communities
        except ImportError:
            logger.warning("networkx not available for community detection")
            return []

        # Get entities and relationships
        entity_query = """
            MATCH (e:Entity {project_id: $project_id})
            RETURN e.uuid AS uuid, e.name AS name
        """

        # Match all relationships between entities, not just RELATES_TO
        # This allows community detection to work with any relationship type
        relationship_query = """
            MATCH (e1:Entity {project_id: $project_id})-[r]->(e2:Entity {project_id: $project_id})
            RETURN e1.uuid AS source, e2.uuid AS target, coalesce(r.weight, 1.0) AS weight
        """

        try:
            entity_result = await self._neo4j_client.execute_query(
                entity_query, project_id=project_id
            )
            rel_result = await self._neo4j_client.execute_query(
                relationship_query, project_id=project_id
            )
        except Exception as e:
            logger.error(f"Failed to fetch graph data: {e}")
            return []

        # Build networkx graph
        G = nx.Graph()

        for record in entity_result.records:
            G.add_node(record["uuid"], name=record["name"])

        for record in rel_result.records:
            G.add_edge(
                record["source"],
                record["target"],
                weight=record.get("weight", 1.0),
            )

        if G.number_of_nodes() < 2:
            logger.debug("Not enough nodes for community detection")
            return []

        # Run Louvain
        try:
            community_sets = louvain_communities(G, weight="weight")
        except Exception as e:
            logger.error(f"Louvain algorithm failed: {e}")
            return []

        # Create community nodes
        communities = []
        for i, member_uuids in enumerate(community_sets):
            if len(member_uuids) < self._min_community_size:
                continue

            community = CommunityNode(
                uuid=str(uuid4()),
                name=f"Community_{i}",
                summary="",
                member_count=len(member_uuids),
                project_id=project_id,
                tenant_id=tenant_id,
            )
            communities.append(community)

        return communities

    async def get_community_members(
        self,
        community_uuid: str,
    ) -> list[dict[str, Any]]:
        """
        Get entity members of a community.

        Args:
            community_uuid: Community UUID

        Returns:
            List of entity dicts
        """
        query = """
            MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {uuid: $uuid})
            RETURN e.uuid AS uuid,
                   e.name AS name,
                   e.entity_type AS entity_type,
                   e.summary AS summary
        """

        result = await self._neo4j_client.execute_query(query, uuid=community_uuid)
        return [dict(record) for record in result.records]

    async def save_community(
        self,
        community: CommunityNode,
        member_uuids: list[str],
    ) -> None:
        """
        Save a community and its member relationships.

        Args:
            community: Community node
            member_uuids: UUIDs of member entities
        """
        # Create community node
        props = community.to_neo4j_properties()

        query = """
            MERGE (c:Community {uuid: $uuid})
            SET c.name = $name,
                c.summary = $summary,
                c.member_count = $member_count,
                c.created_at = datetime($created_at),
                c.tenant_id = $tenant_id,
                c.project_id = $project_id
        """

        await self._neo4j_client.execute_query(query, **props)

        # Create BELONGS_TO relationships
        if member_uuids:
            rel_query = """
                MATCH (c:Community {uuid: $community_uuid})
                UNWIND $member_uuids AS member_uuid
                MATCH (e:Entity {uuid: member_uuid})
                MERGE (e)-[:BELONGS_TO]->(c)
            """

            await self._neo4j_client.execute_query(
                rel_query,
                community_uuid=community.uuid,
                member_uuids=member_uuids,
            )

    async def delete_stale_communities(
        self,
        project_id: str,
    ) -> int:
        """
        Delete communities that no longer have any members.

        Args:
            project_id: Project ID

        Returns:
            Number of communities deleted
        """
        query = """
            MATCH (c:Community {project_id: $project_id})
            WHERE NOT EXISTS {
                MATCH (e:Entity)-[:BELONGS_TO]->(c)
            }
            DETACH DELETE c
            RETURN count(c) AS deleted
        """

        result = await self._neo4j_client.execute_query(query, project_id=project_id)

        if result.records:
            deleted = result.records[0]["deleted"]
            logger.info(f"Deleted {deleted} stale communities for project {project_id}")
            return cast(int, deleted)

        return 0
