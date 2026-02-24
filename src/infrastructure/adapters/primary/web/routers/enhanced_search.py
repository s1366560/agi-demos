"""Enhanced search API routes with advanced filtering and capabilities."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from src.domain.ports.services.graph_service_port import GraphServicePort

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graph_service,
    get_neo4j_client,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

# Main router for enhanced search endpoints
router = APIRouter(prefix="/api/v1/search-enhanced", tags=["search-enhanced"])

# Secondary router for memory search compatibility (moved from graph.py)
memory_router = APIRouter(prefix="/api/v1", tags=["memory-search"])

# Hybrid router
hybrid_router = APIRouter(prefix="/api/v1/hybrid", tags=["hybrid-search"])


# --- Endpoints ---


@router.post("/advanced")
async def search_advanced(
    query: str = Body(..., description="Search query"),
    strategy: str = Body("COMBINED_HYBRID_SEARCH_RRF", description="Search strategy recipe name"),
    focal_node_uuid: str | None = Body(
        None, description="Focal node UUID for Node Distance Reranking"
    ),
    reranker: str | None = Body(None, description="Reranker client (openai, gemini, bge)"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    tenant_id: str | None = Body(None, description="Tenant filter"),
    project_id: str | None = Body(None, description="Project filter"),
    since: str | None = Body(None, description="Filter by creation date (ISO format)"),
    current_user: User = Depends(get_current_user),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
) -> dict[str, Any]:
    """
    Perform advanced search with configurable strategy and reranking.

    Uses NativeGraphAdapter's hybrid search (vector + keyword + RRF fusion).
    """
    logger.info(f"search_advanced called: query='{query}', project_id='{project_id}'")
    try:
        if not graph_service:
            raise HTTPException(status_code=503, detail="Graph service not available")

        # Use NativeGraphAdapter's search method
        results = await graph_service.search(
            query=query,
            project_id=project_id,
            limit=limit,
        )

        # Convert results to response format
        formatted_results = []
        for idx, item in enumerate(results):
            item_type = item.get("type", "unknown")
            score = 1.0 - (idx * 0.01)  # Simple scoring based on position

            if item_type == "episode":
                formatted_results.append(
                    {
                        "content": item.get("content", ""),
                        "score": score,
                        "source": "Episode",
                        "type": "Episode",
                        "metadata": {
                            "uuid": item.get("uuid", ""),
                            "name": item.get("name", ""),
                            "type": "Episode",
                        },
                    }
                )
            else:
                formatted_results.append(
                    {
                        "content": item.get("summary", "") or item.get("name", ""),
                        "score": score,
                        "source": "Knowledge Graph",
                        "type": "Entity",
                        "metadata": {
                            "uuid": item.get("uuid", ""),
                            "name": item.get("name", ""),
                            "entity_type": item.get("entity_type", "Entity"),
                        },
                    }
                )

        return {
            "results": formatted_results,
            "total": len(formatted_results),
            "search_type": "advanced",
            "strategy": strategy,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Advanced search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/graph-traversal")
async def search_by_graph_traversal(
    start_entity_uuid: str = Body(..., description="Starting entity UUID"),
    max_depth: int = Body(2, ge=1, le=5, description="Maximum traversal depth"),
    relationship_types: list[str] | None = Body(None, description="Relationship types to follow"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    tenant_id: str | None = Body(None, description="Tenant filter"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
) -> dict[str, Any]:
    """
    Search by traversing the knowledge graph from a starting entity.

    This performs graph traversal to find related entities, episodes, and communities.
    Useful for exploring connections and discovering related content.
    """
    try:
        if not neo4j_client:
            raise HTTPException(status_code=503, detail="Neo4j client not available")

        # Build relationship type filter
        rel_filter = ""
        if relationship_types:
            rel_filter = "AND type(r) IN [{}]".format(
                ", ".join([f'"{t}"' for t in relationship_types])
            )

        query = f"""
        MATCH path = (start:Entity {{uuid: $uuid}})-[*1..{max_depth}]-(related)
        WHERE ('Entity' IN labels(related) OR 'Episodic' IN labels(related) OR 'Community' IN labels(related))
        {rel_filter}
        RETURN DISTINCT related, properties(related) as props, labels(related) as labels
        LIMIT $limit
        """

        result = await neo4j_client.execute_query(query, uuid=start_entity_uuid, limit=limit)

        items = []
        for r in result.records:
            props = r["props"]
            labels = r["labels"]

            # Extract specific entity type from labels (exclude base labels)
            ignored_labels = {"Entity", "Node", "BaseEntity"}
            specific_labels = [label for label in labels if label and label not in ignored_labels]
            entity_type = (
                specific_labels[0] if specific_labels else (labels[0] if labels else "Entity")
            )

            logger.debug(
                f"Graph traversal - Node {props.get('uuid')} with labels: {labels} -> entity_type: {entity_type}"
            )

            items.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "type": entity_type,  # At root level
                    "summary": props.get("summary", ""),
                    "content": props.get("content", ""),
                    "created_at": props.get("created_at"),
                    "metadata": {
                        "uuid": props.get("uuid", ""),
                        "name": props.get("name", ""),
                        "type": entity_type,  # Also in metadata for consistency
                        "created_at": props.get("created_at"),
                    },
                }
            )

        return {
            "results": items,
            "total": len(items),
            "search_type": "graph_traversal",
        }

    except Exception as e:
        logger.error(f"Graph traversal search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/community")
async def search_by_community(
    community_uuid: str = Body(..., description="Community UUID"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    include_episodes: bool = Body(True, description="Include episodes in results"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
) -> dict[str, Any]:
    """
    Search within a community for related content.

    This finds all entities and optionally episodes within a specific community.
    """
    try:
        if not neo4j_client:
            raise HTTPException(status_code=503, detail="Neo4j client not available")

        # Get entities in community
        entity_query = """
        MATCH (c:Community {uuid: $uuid})
        MATCH (e:Entity)-[:BELONGS_TO]->(c)
        RETURN properties(e) as props, 'Entity' as type
        """

        result = await neo4j_client.execute_query(entity_query, uuid=community_uuid)

        items = []
        for r in result.records:
            props = r["props"]
            items.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "type": "entity",
                    "summary": props.get("summary", ""),
                    "created_at": props.get("created_at"),
                }
            )

        # Optionally include episodes
        if include_episodes:
            episode_query = """
            MATCH (c:Community {uuid: $uuid})
            MATCH (e:Entity)-[:BELONGS_TO]->(c)
            MATCH (ep:Episodic)-[:MENTIONS]->(e)
            RETURN DISTINCT properties(ep) as props, 'Episodic' as type
            LIMIT $limit
            """

            ep_result = await neo4j_client.execute_query(
                episode_query, uuid=community_uuid, limit=limit
            )

            for r in ep_result.records:
                props = r["props"]
                items.append(
                    {
                        "uuid": props.get("uuid", ""),
                        "name": props.get("name", ""),
                        "type": "episode",
                        "content": props.get("content", ""),
                        "created_at": props.get("created_at"),
                    }
                )

        return {
            "results": items[:limit],
            "total": len(items),
            "search_type": "community",
        }

    except Exception as e:
        logger.error(f"Community search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/temporal")
async def search_temporal(
    query: str = Body(..., description="Search query"),
    since: str | None = Body(None, description="Start of time range (ISO format)"),
    until: str | None = Body(None, description="End of time range (ISO format)"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    tenant_id: str | None = Body(None, description="Tenant filter"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
) -> dict[str, Any]:
    """
    Search within a temporal window.

    Performs semantic search restricted to a specific time range.
    Useful for finding memories from specific periods.
    """
    try:
        parsed_since = None
        parsed_until = None

        if since:
            try:
                parsed_since = datetime.fromisoformat(since)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid 'since' datetime format"
                ) from None

        if until:
            try:
                parsed_until = datetime.fromisoformat(until)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid 'until' datetime format"
                ) from None

        # Build temporal filter
        conditions = []
        params = {"query": query, "limit": limit}

        if parsed_since:
            conditions.append("e.created_at >= datetime($since)")
            params["since"] = parsed_since.isoformat()

        if parsed_until:
            conditions.append("e.created_at <= datetime($until)")
            params["until"] = parsed_until.isoformat()

        if tenant_id:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        search_query = f"""
        MATCH (e:Episodic)
        {where_clause}
        RETURN properties(e) as props, 'episode' as type
        ORDER BY e.created_at DESC
        LIMIT $limit
        """

        result = await neo4j_client.execute_query(search_query, **params)

        items = []
        for r in result.records:
            props = r["props"]
            items.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "type": "episode",
                    "content": props.get("content", ""),
                    "created_at": props.get("created_at"),
                }
            )

        return {
            "results": items,
            "total": len(items),
            "search_type": "temporal",
            "time_range": {
                "since": since,
                "until": until,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Temporal search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/faceted")
async def search_with_facets(
    query: str = Body(..., description="Search query"),
    entity_types: list[str] | None = Body(None, description="Filter by entity types"),
    tags: list[str] | None = Body(None, description="Filter by tags"),
    since: str | None = Body(None, description="Filter by creation date (ISO format)"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    offset: int = Body(0, ge=0, description="Pagination offset"),
    tenant_id: str | None = Body(None, description="Tenant filter"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
) -> dict[str, Any]:
    """
    Search with faceted filtering.

    Performs semantic search with additional filters and returns facet counts
    for UI filtering controls.
    """
    try:
        parsed_since = None
        if since:
            try:
                parsed_since = datetime.fromisoformat(since)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid 'since' datetime format"
                ) from None

        # Build filters
        conditions = []
        params = {"limit": limit, "offset": offset}

        if entity_types:
            conditions.append("e.entity_type IN $entity_types")
            params["entity_types"] = entity_types

        if parsed_since:
            conditions.append("e.created_at >= datetime($since)")
            params["since"] = parsed_since.isoformat()

        if tenant_id:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = tenant_id

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        search_query = f"""
        MATCH (e:Entity)
        {where_clause}
        RETURN properties(e) as props, labels(e) as labels, 'entity' as type
        SKIP $offset
        LIMIT $limit
        """

        result = await neo4j_client.execute_query(search_query, **params)

        items = []
        for r in result.records:
            props = r["props"]
            labels = r["labels"]

            # Extract specific entity type from labels (exclude base labels)
            ignored_labels = {"Entity", "Node", "BaseEntity"}
            specific_labels = [label for label in labels if label and label not in ignored_labels]
            entity_type = specific_labels[0] if specific_labels else "Entity"

            logger.debug(
                f"Faceted search - Node {props.get('uuid')} with labels: {labels} -> entity_type: {entity_type}"
            )

            items.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "type": entity_type,  # Use actual entity type at root level
                    "entity_type": entity_type,
                    "summary": props.get("summary", ""),
                    "created_at": props.get("created_at"),
                    "metadata": {
                        "uuid": props.get("uuid", ""),
                        "name": props.get("name", ""),
                        "type": entity_type,
                        "created_at": props.get("created_at"),
                    },
                }
            )

        # Compute facets
        facets = {"entity_types": {}, "total": len(items)}

        for item in items:
            et = item.get("entity_type", "Entity")
            facets["entity_types"][et] = facets["entity_types"].get(et, 0) + 1

        return {
            "results": items,
            "facets": facets,
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "search_type": "faceted",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Faceted search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/capabilities")
async def get_search_capabilities(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """
    Get available search capabilities and configuration.

    Returns information about available search types and their parameters.
    """
    return {
        "search_types": {
            "semantic": {
                "description": "Semantic search using embeddings and hybrid retrieval",
                "endpoint": "/api/v1/memory/search",
                "parameters": {
                    "query": "string (required)",
                    "limit": "integer (1-100)",
                    "tenant_id": "string (optional)",
                    "project_id": "string (optional)",
                },
            },
            "graph_traversal": {
                "description": "Search by traversing the knowledge graph",
                "endpoint": "/api/v1/search-enhanced/graph-traversal",
                "parameters": {
                    "start_entity_uuid": "string (required)",
                    "max_depth": "integer (1-5)",
                    "relationship_types": "array of strings (optional)",
                    "limit": "integer (1-200)",
                },
            },
            "community": {
                "description": "Search within a specific community",
                "endpoint": "/api/v1/search-enhanced/community",
                "parameters": {
                    "community_uuid": "string (required)",
                    "limit": "integer (1-200)",
                    "include_episodes": "boolean",
                },
            },
            "temporal": {
                "description": "Search within a time range",
                "endpoint": "/api/v1/search-enhanced/temporal",
                "parameters": {
                    "query": "string (required)",
                    "since": "ISO datetime string (optional)",
                    "until": "ISO datetime string (optional)",
                    "limit": "integer (1-200)",
                },
            },
            "faceted": {
                "description": "Search with faceted filtering",
                "endpoint": "/api/v1/search-enhanced/faceted",
                "parameters": {
                    "query": "string (required)",
                    "entity_types": "array of strings (optional)",
                    "tags": "array of strings (optional)",
                    "since": "ISO datetime string (optional)",
                    "limit": "integer (1-200)",
                    "offset": "integer (0+)",
                },
            },
        },
        "filters": {
            "entity_types": [
                "Person",
                "Organization",
                "Product",
                "Location",
                "Event",
                "Concept",
                "Custom",
            ],
            "relationship_types": [
                "RELATES_TO",
                "MENTIONS",
                "PART_OF",
                "CONTAINS",
                "BELONGS_TO",
                "OWNS",
                "LOCATED_AT",
            ],
        },
    }


# --- Memory Search Endpoint (moved from graph.py) ---


@memory_router.post("/memory/search")
async def memory_search(
    params: dict[str, Any],
    current_user: User = Depends(get_current_user),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
) -> dict[str, Any]:
    """
    Search memories using hybrid search.

    This endpoint consolidates search functionality.
    Supports semantic search, keyword search, and graph traversal.
    """
    try:
        query = params.get("query", "")
        limit = params.get("limit", 10)
        project_id = params.get("project_id") or params.get("tenant_id")

        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        if not graph_service:
            raise HTTPException(status_code=503, detail="Graph service not available")

        # Use NativeGraphAdapter's search method
        results = await graph_service.search(
            query=query,
            project_id=project_id,
            limit=limit,
        )

        # Convert results to response format
        formatted_results = []
        for idx, item in enumerate(results):
            item_type = item.get("type", "unknown")
            score = 1.0 - (idx * 0.01)  # Simple scoring based on position

            if item_type == "episode":
                formatted_results.append(
                    {
                        "uuid": item.get("uuid", ""),
                        "name": item.get("name", ""),
                        "content": item.get("content", ""),
                        "type": "episode",
                        "score": score,
                        "created_at": item.get("created_at"),
                        "metadata": {
                            "source": item.get("source", ""),
                            "source_description": item.get("source_description", ""),
                        },
                    }
                )
            else:
                formatted_results.append(
                    {
                        "uuid": item.get("uuid", ""),
                        "name": item.get("name", ""),
                        "summary": item.get("summary", ""),
                        "content": item.get("summary", ""),
                        "type": "entity",
                        "entity_type": item.get("entity_type", "Unknown"),
                        "score": score,
                        "created_at": item.get("created_at"),
                        "metadata": {},
                    }
                )

        return {
            "results": formatted_results,
            "total": len(formatted_results),
            "query": query,
            "filters_applied": {"project_id": project_id} if project_id else {},
            "search_metadata": {"strategy": "hybrid_search", "limit": limit},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
