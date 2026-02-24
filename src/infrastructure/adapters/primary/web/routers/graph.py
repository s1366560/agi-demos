"""Knowledge Graph API routes.

This router provides endpoints for accessing and manipulating the knowledge graph structure,
including communities, entities, and graph visualizations. Search functionality has been
moved to enhanced_search.py to avoid duplication.
"""

import logging
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.domain.ports.services.graph_service_port import GraphServicePort
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graph_service,
    get_neo4j_client,
    get_workflow_engine,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


def _serialize_datetime(value: Any) -> str | None:
    """Convert Neo4j DateTime to ISO string for JSON serialization."""
    if value is None:
        return None
    # Neo4j DateTime has isoformat() method
    if hasattr(value, "isoformat"):
        return value.isoformat()
    # Fallback to string conversion
    return str(value) if value else None


# --- Schemas ---


class Entity(BaseModel):
    uuid: str
    name: str
    entity_type: str
    summary: str
    tenant_id: str | None = None
    project_id: str | None = None
    created_at: str | None = None


class Community(BaseModel):
    uuid: str
    name: str
    summary: str
    member_count: int
    tenant_id: str | None = None
    project_id: str | None = None
    formed_at: str | None = None
    created_at: str | None = None


class GraphData(BaseModel):
    elements: dict


class SubgraphRequest(BaseModel):
    node_uuids: list[str]
    include_neighbors: bool = True
    limit: int = 100
    tenant_id: str | None = None
    project_id: str | None = None


# --- Graph Structure Endpoints ---


@router.get("/communities/")
async def list_communities(
    project_id: str | None = None,
    min_members: int | None = Query(None, description="Minimum member count"),
    limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """
    List communities in the knowledge graph with filtering and pagination.

    Note: Communities are now associated with projects via project_id (which equals group_id).
    If project_id is provided, filters by that project. Otherwise, returns all communities.
    """
    try:
        conditions = ["coalesce(c.member_count, 0) >= 0"]  # Always include base condition
        params = {"limit": limit, "offset": offset}

        # Filter by project_id if provided
        if project_id:
            conditions.append("c.project_id = $project_id")
            params["project_id"] = project_id

        if min_members is not None:
            conditions.append("coalesce(c.member_count, 0) >= $min_members")
            params["min_members"] = min_members

        where_clause = "WHERE " + " AND ".join(conditions)

        # Count query
        count_query = f"""
        MATCH (c:Community)
        {where_clause}
        RETURN count(c) as total
        """
        logger.info(f"Counting communities with project_id={project_id}")
        count_result = await neo4j_client.execute_query(count_query, **params)
        total = count_result.records[0]["total"] if count_result.records else 0
        logger.info(f"Found {total} communities")

        # List query
        list_query = f"""
        MATCH (c:Community)
        {where_clause}
        RETURN properties(c) as props
        ORDER BY coalesce(c.member_count, 0) DESC
        SKIP $offset
        LIMIT $limit
        """

        result = await neo4j_client.execute_query(list_query, **params)

        communities = []
        for r in result.records:
            props = r["props"]
            communities.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "summary": props.get("summary", ""),
                    "member_count": props.get("member_count", 0),
                    "tenant_id": props.get("tenant_id"),
                    "project_id": props.get("project_id"),
                    "formed_at": _serialize_datetime(props.get("formed_at")),
                    "created_at": _serialize_datetime(props.get("created_at")),
                }
            )

        logger.info(f"Returning {len(communities)} communities (offset={offset}, limit={limit})")

        return {"communities": communities, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        logger.error(f"Failed to list communities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/entities/")
async def list_entities(
    project_id: str | None = None,
    entity_type: str | None = Query(None, description="Filter by entity type"),
    limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """List entities in the knowledge graph with filtering and pagination."""
    try:
        conditions = []
        params = {"limit": limit, "offset": offset}

        if project_id:
            project_condition = """
            (
                e.project_id = $project_id OR
                EXISTS {
                    MATCH (e)<-[:MENTIONS]-(ep:Episodic)
                    WHERE ep.project_id = $project_id
                }
            )
            """
            conditions.append(project_condition)
            params["project_id"] = project_id

        if entity_type:
            # Filter by entity type using label filtering
            conditions.append("'$entity_type' IN labels(e)")
            params["entity_type"] = entity_type

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Count
        count_query = f"MATCH (e:Entity) {where_clause} RETURN count(e) as total"
        count_result = await neo4j_client.execute_query(count_query, **params)
        total = count_result.records[0]["total"] if count_result.records else 0

        # List
        list_query = f"""
        MATCH (e:Entity)
        {where_clause}
        RETURN properties(e) as props, labels(e) as labels
        ORDER BY e.created_at DESC
        SKIP $offset
        LIMIT $limit
        """

        result = await neo4j_client.execute_query(list_query, **params)

        entities = []
        for r in result.records:
            props = r["props"]
            # Get entity_type from props (not from labels - entity_type is a property)
            e_type = props.get("entity_type", "Entity")

            entities.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "entity_type": e_type,
                    "summary": props.get("summary", ""),
                    "tenant_id": props.get("tenant_id"),
                    "project_id": props.get("project_id"),
                    "created_at": _serialize_datetime(props.get("created_at")),
                }
            )

        return {"entities": entities, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        logger.error(f"Failed to list entities: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/entities/types")
async def get_entity_types(
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """
    Get all available entity types with their counts.

    Useful for populating filter dropdowns with dynamic entity types.
    """
    try:
        conditions = []
        params = {}

        if project_id:
            conditions.append(
                "(e.project_id = $project_id OR EXISTS { MATCH (e)<-[:MENTIONS]-(ep:Episodic) WHERE ep.project_id = $project_id })"
            )
            params["project_id"] = project_id

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
        MATCH (e:Entity)
        {where_clause}
        UNWIND labels(e) as label
        WITH label, count(e) as entity_count
        WHERE label <> 'Entity' AND label <> 'Node' AND label <> 'BaseEntity'
        RETURN label as entity_type, entity_count
        ORDER BY entity_count DESC
        """

        result = await neo4j_client.execute_query(query, **params)

        entity_types = []
        for r in result.records:
            entity_types.append({"entity_type": r["entity_type"], "count": r["entity_count"]})

        return {"entity_types": entity_types, "total": len(entity_types)}
    except Exception as e:
        logger.error(f"Failed to get entity types: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: str,
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """
    Get entity details by UUID.

    Args:
        entity_id: Entity UUID

    Returns:
        Entity details with properties
    """
    try:
        query = """
        MATCH (e:Entity {uuid: $uuid})
        RETURN properties(e) as props, labels(e) as labels
        """

        result = await neo4j_client.execute_query(query, uuid=entity_id)

        if not result.records:
            raise HTTPException(status_code=404, detail="Entity not found")

        props = result.records[0]["props"]

        # Get entity_type from props (not from labels - entity_type is a property)
        e_type = props.get("entity_type", "Entity")

        return {
            "uuid": props.get("uuid", ""),
            "name": props.get("name", ""),
            "entity_type": e_type,
            "summary": props.get("summary", ""),
            "description": props.get("description", ""),
            "tenant_id": props.get("tenant_id"),
            "project_id": props.get("project_id"),
            "created_at": _serialize_datetime(props.get("created_at")),
            "updated_at": _serialize_datetime(props.get("updated_at")),
            "properties": {
                k: v
                for k, v in props.items()
                if k
                not in [
                    "uuid",
                    "name",
                    "summary",
                    "description",
                    "tenant_id",
                    "project_id",
                    "created_at",
                    "updated_at",
                ]
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get entity {entity_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/entities/{entity_id}/relationships")
async def get_entity_relationships(
    entity_id: str,
    relationship_type: str | None = Query(None, description="Filter by relationship type"),
    limit: int = Query(50, ge=1, le=200, description="Maximum relationships to return"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """
    Get relationships for an entity.

    Returns both outgoing and incoming relationships for the specified entity.

    Args:
        entity_id: Entity UUID
        relationship_type: Optional relationship type filter
        limit: Maximum relationships to return

    Returns:
        List of relationships with source and target entities
    """
    try:
        # Build relationship type filter
        rel_filter = ""
        params = {"uuid": entity_id, "limit": limit}

        if relationship_type:
            rel_filter = "AND type(r) = $relationship_type"
            params["relationship_type"] = relationship_type

        # Query for both outgoing and incoming relationships
        query = f"""
        MATCH (e:Entity {{uuid: $uuid}})
        OPTIONAL MATCH (e)-[r]-(related:Entity)
        WHERE related IS NOT NULL {rel_filter}
        RETURN
            elementId(r) as edge_id,
            type(r) as relation_type,
            properties(r) as edge_props,
            startNode(r) as start_node,
            endNode(r) as end_node,
            properties(related) as related_props,
            labels(related) as related_labels,
            CASE
                WHEN startNode(r).uuid = $uuid THEN 'outgoing'
                ELSE 'incoming'
            END as direction
        LIMIT $limit
        """

        result = await neo4j_client.execute_query(query, **params)

        relationships = []
        for r in result.records:
            edge_props = r["edge_props"] or {}
            related_props = r["related_props"]
            related_labels = r["related_labels"]

            # Get related entity type
            related_type = next((label for label in related_labels if label != "Entity"), "Unknown")

            # Clean up edge properties (remove embeddings)
            if "fact_embedding" in edge_props:
                edge_props = {k: v for k, v in edge_props.items() if k != "fact_embedding"}

            relationships.append(
                {
                    "edge_id": r["edge_id"],
                    "relation_type": r["relation_type"],
                    "direction": r["direction"],
                    "fact": edge_props.get("fact", ""),
                    "score": edge_props.get("score", 0.0),
                    "created_at": _serialize_datetime(edge_props.get("created_at")),
                    "updated_at": _serialize_datetime(edge_props.get("updated_at")),
                    "related_entity": {
                        "uuid": related_props.get("uuid", ""),
                        "name": related_props.get("name", ""),
                        "entity_type": related_type,
                        "summary": related_props.get("summary", ""),
                        "created_at": _serialize_datetime(related_props.get("created_at")),
                    },
                }
            )

        return {"relationships": relationships, "total": len(relationships)}
    except Exception as e:
        logger.error(f"Failed to get relationships for entity {entity_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/memory/graph")
async def get_graph(
    project_id: str | None = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """Get graph data for visualization."""
    try:
        query = """
        MATCH (n)
        WHERE ('Entity' IN labels(n) OR 'Episodic' IN labels(n) OR 'Community' IN labels(n))
        AND ($project_id IS NULL OR n.project_id = $project_id)

        OPTIONAL MATCH (n)-[r]->(m)
        WHERE ('Entity' IN labels(m) OR 'Episodic' IN labels(m) OR 'Community' IN labels(m))

        RETURN
            elementId(n) as source_id, labels(n) as source_labels, properties(n) as source_props,
            elementId(r) as edge_id, type(r) as edge_type, properties(r) as edge_props,
            elementId(m) as target_id, labels(m) as target_labels, properties(m) as target_props
        LIMIT $limit
        """

        result = await neo4j_client.execute_query(query, project_id=project_id, limit=limit)

        nodes_map = {}
        edges_list = []

        for r in result.records:
            s_id = r["source_id"]
            s_props = r["source_props"]
            if "name_embedding" in s_props:
                del s_props["name_embedding"]

            if s_id not in nodes_map:
                nodes_map[s_id] = {
                    "data": {
                        "id": s_id,
                        "label": r["source_labels"][0] if r["source_labels"] else "Entity",
                        "name": s_props.get("name", "Unknown"),
                        **s_props,
                    }
                }

            if r["target_id"]:
                t_id = r["target_id"]
                t_props = r["target_props"]
                if "name_embedding" in t_props:
                    del t_props["name_embedding"]

                if t_id not in nodes_map:
                    nodes_map[t_id] = {
                        "data": {
                            "id": t_id,
                            "label": r["target_labels"][0] if r["target_labels"] else "Entity",
                            "name": t_props.get("name", "Unknown"),
                            **t_props,
                        }
                    }

                if r["edge_id"]:
                    e_props = r["edge_props"]
                    if "fact_embedding" in e_props:
                        del e_props["fact_embedding"]

                    edges_list.append(
                        {
                            "data": {
                                "id": r["edge_id"],
                                "source": s_id,
                                "target": t_id,
                                "label": r["edge_type"],
                                **e_props,
                            }
                        }
                    )

        return {"elements": {"nodes": list(nodes_map.values()), "edges": edges_list}}
    except Exception as e:
        logger.error(f"Failed to get graph: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/memory/graph/subgraph")
async def get_subgraph(
    params: SubgraphRequest,
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """Get subgraph for specific nodes."""
    try:
        project_id = params.project_id

        query = """
        MATCH (n)
        WHERE n.uuid IN $node_uuids
        AND ($project_id IS NULL OR n.project_id = $project_id)

        WITH n
        """

        if params.include_neighbors:
            query += """
            OPTIONAL MATCH (n)-[r]-(m)
            WHERE ('Entity' IN labels(m) OR 'Episodic' IN labels(m) OR 'Community' IN labels(m))
            RETURN
                elementId(n) as source_id, labels(n) as source_labels, properties(n) as source_props,
                elementId(r) as edge_id, type(r) as edge_type, properties(r) as edge_props,
                elementId(m) as target_id, labels(m) as target_labels, properties(m) as target_props
            LIMIT $limit
            """
        else:
            query += """
            RETURN
                elementId(n) as source_id, labels(n) as source_labels, properties(n) as source_props,
                null as edge_id, null as edge_type, null as edge_props,
                null as target_id, null as target_labels, null as target_props
            LIMIT $limit
            """

        result = await neo4j_client.execute_query(
            query, node_uuids=params.node_uuids, project_id=project_id, limit=params.limit
        )

        nodes_map = {}
        edges_list = []

        for r in result.records:
            # Process source node
            s_id = r["source_id"]
            if s_id:
                s_props = r["source_props"]
                if "name_embedding" in s_props:
                    del s_props["name_embedding"]

                if s_id not in nodes_map:
                    nodes_map[s_id] = {
                        "data": {
                            "id": s_id,
                            "label": r["source_labels"][0] if r["source_labels"] else "Entity",
                            "name": s_props.get("name", "Unknown"),
                            **s_props,
                        }
                    }

            # Process target node and edge if available
            if r.get("target_id"):
                t_id = r["target_id"]
                t_props = r["target_props"]
                if "name_embedding" in t_props:
                    del t_props["name_embedding"]

                if t_id not in nodes_map:
                    nodes_map[t_id] = {
                        "data": {
                            "id": t_id,
                            "label": r["target_labels"][0] if r["target_labels"] else "Entity",
                            "name": t_props.get("name", "Unknown"),
                            **t_props,
                        }
                    }

                if r.get("edge_id"):
                    e_props = r["edge_props"] or {}
                    if "fact_embedding" in e_props:
                        del e_props["fact_embedding"]

                    edges_list.append(
                        {
                            "data": {
                                "id": r["edge_id"],
                                "source": s_id,
                                "target": t_id,
                                "label": r["edge_type"],
                                **e_props,
                            }
                        }
                    )

        return {"elements": {"nodes": list(nodes_map.values()), "edges": edges_list}}
    except Exception as e:
        logger.error(f"Failed to get subgraph: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Community Detail Endpoints ---


@router.get("/communities/{community_id}")
async def get_community(
    community_id: str,
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """
    Get community details by UUID.

    Args:
        community_id: Community UUID

    Returns:
        Community details with properties
    """
    try:
        query = """
        MATCH (c:Community {uuid: $uuid})
        RETURN properties(c) as props
        """

        result = await neo4j_client.execute_query(query, uuid=community_id)

        if not result.records:
            raise HTTPException(status_code=404, detail="Community not found")

        props = result.records[0]["props"]

        return {
            "uuid": props.get("uuid", ""),
            "name": props.get("name", ""),
            "summary": props.get("summary", ""),
            "member_count": props.get("member_count", 0),
            "tenant_id": props.get("tenant_id"),
            "project_id": props.get("project_id"),
            "formed_at": _serialize_datetime(props.get("formed_at")),
            "created_at": _serialize_datetime(props.get("created_at")),
            "updated_at": _serialize_datetime(props.get("updated_at")),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get community {community_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/communities/{community_id}/members")
async def get_community_members(
    community_id: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum members to return"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
):
    """
    Get members (entities) of a community.

    Args:
        community_id: Community UUID
        limit: Maximum members to return

    Returns:
        List of community members with their details
    """
    try:
        # Note: Entity-[:BELONGS_TO]->Community (not Community-[:HAS_MEMBER]->Entity)
        query = """
        MATCH (e:Entity)-[:BELONGS_TO]->(c:Community {uuid: $uuid})
        RETURN properties(e) as props
        LIMIT $limit
        """

        result = await neo4j_client.execute_query(query, uuid=community_id, limit=limit)

        members = []
        for r in result.records:
            props = r["props"]
            # Get entity_type from props (not from labels)
            e_type = props.get("entity_type", "Entity")

            members.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "entity_type": e_type,
                    "summary": props.get("summary", ""),
                    "created_at": _serialize_datetime(props.get("created_at")),
                }
            )

        return {"members": members, "total": len(members)}
    except Exception as e:
        logger.error(f"Failed to get members for community {community_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/communities/rebuild")
async def rebuild_communities(
    background: bool = Query(False, description="Run in background mode"),
    project_id: str | None = Query(None, description="Project ID to rebuild communities for"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None=Depends(get_neo4j_client),
    workflow_engine: WorkflowEnginePort=Depends(get_workflow_engine),
    graph_service: GraphServicePort | None=Depends(get_graph_service),
):
    """
    Rebuild communities using the Louvain algorithm for the specified project.

    This will:
    1. Remove all existing community nodes and relationships for the current project
    2. Detect new communities using label propagation (scoped to project)
    3. Generate community summaries using LLM
    4. Generate embeddings for community nodes
    5. Set project_id = group_id for proper project association
    6. Calculate member_count using Neo4j 5.x compatible syntax

    Warning: This is an expensive operation that may take several minutes
    depending on the size of your graph.

    Set background=true to run asynchronously and return a task ID for tracking.
    The task can then be monitored via GET /api/v1/tasks/{task_id}
    """
    from datetime import datetime
    from uuid import uuid4

    # Get project_id from query parameter, or fall back to user's default project
    target_project_id = project_id or getattr(current_user, "project_id", None) or "neo4j"

    # Execute either synchronously or submit to background workflow
    if background:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.models import TaskLog

        # Create task payload
        task_payload = {
            "task_group_id": target_project_id,
            "project_id": target_project_id,
        }

        # Create TaskLog record
        task_id = str(uuid4())
        async with async_session_factory() as session, session.begin():
            task_log = TaskLog(
                id=task_id,
                group_id=target_project_id,
                task_type="rebuild_communities",
                status="PENDING",
                payload=task_payload,
                entity_type="community",
                created_at=datetime.now(UTC),
            )
            session.add(task_log)

        # Add task_id to payload for progress tracking
        task_payload["task_id"] = task_id

        # Start Temporal workflow
        workflow_id = f"rebuild-communities-{target_project_id}-{task_id[:8]}"

        await workflow_engine.start_workflow(
            workflow_name="rebuild_communities",
            workflow_id=workflow_id,
            input_data=task_payload,
            task_queue="default",
        )

        logger.info(
            f"Submitted community rebuild task {task_id} for background execution "
            f"(project: {target_project_id}, workflow_id={workflow_id})"
        )

        return {
            "status": "submitted",
            "message": "Community rebuild started in background",
            "task_id": task_id,
            "workflow_id": workflow_id,
            "task_url": f"/api/v1/tasks/{task_id}",
        }
    else:
        # For synchronous execution, use the graph service directly
        from src.infrastructure.graph.schemas import EntityNode

        if not graph_service:
            raise HTTPException(status_code=500, detail="Graph service not initialized")

        try:
            # Remove existing communities
            await neo4j_client.execute_query(
                """
                MATCH (c:Community)
                WHERE c.project_id = $project_id OR c.group_id = $project_id
                DETACH DELETE c
                """,
                project_id=target_project_id,
            )

            # Get entities for this project
            entity_result = await neo4j_client.execute_query(
                """
                MATCH (e:Entity)
                WHERE e.project_id = $project_id
                RETURN e.uuid as uuid, e.name as name, e.entity_type as entity_type
                LIMIT 1000
                """,
                project_id=target_project_id,
            )

            entities = []
            for record in entity_result.records:
                entity = EntityNode(
                    uuid=record["uuid"],
                    name=record["name"],
                    entity_type=record.get("entity_type", "unknown"),
                    project_id=target_project_id,
                )
                entities.append(entity)

            # Use community updater if available
            communities_count = 0
            if hasattr(graph_service, "community_updater"):
                communities = await graph_service.community_updater.update_communities_for_entities(
                    entities=entities,
                    project_id=target_project_id,
                    regenerate_all=True,
                )
                communities_count = len(communities) if communities else 0

            return {
                "status": "success",
                "message": "Communities rebuilt successfully",
                "communities_count": communities_count,
                "entities_processed": len(entities),
            }
        except Exception as e:
            logger.error(f"Failed to rebuild communities: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to rebuild communities: {e!s}"
            ) from e
