"""Enhanced search API routes with advanced filtering and capabilities."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.graph_store_port import (
    GraphStorePort,
    GraphStorePort as GraphServicePort,
)
from src.domain.ports.services.retrieval_store_port import RetrievalStorePort

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graph_store,
    get_graph_store as get_graph_service,
    get_retrieval_store,
)
from src.infrastructure.adapters.primary.web.routers.graph import (
    _ensure_graph_project_access,
    _entity_type_from_props_or_labels,
    _graph_project_scope,
    _sanitize_graph_value,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

# Main router for enhanced search endpoints
router = APIRouter(prefix="/api/v1/search-enhanced", tags=["search-enhanced"])

# Secondary router for memory search compatibility (moved from graph.py)
memory_router = APIRouter(prefix="/api/v1", tags=["memory-search"])

# Hybrid router
hybrid_router = APIRouter(prefix="/api/v1/hybrid", tags=["hybrid-search"])


async def _search_graph_service_for_scope(
    graph_service: GraphServicePort,
    query: str,
    tenant_id: str | None,
    project_id: str | None,
    limit: int,
    current_user: User,
    db: AsyncSession,
) -> list[Any]:
    if project_id:
        _ = await _graph_project_scope(project_id, current_user, db, tenant_id=tenant_id)
        return await graph_service.search(query=query, project_id=project_id, limit=limit)

    if tenant_id:
        allowed_project_ids = await _tenant_search_project_ids(tenant_id, current_user, db)
        return await _search_graph_service_projects(
            graph_service,
            query=query,
            project_ids=allowed_project_ids,
            limit=limit,
        )

    is_superuser, allowed_project_ids = await _graph_project_scope(None, current_user, db)
    if is_superuser:
        return await graph_service.search(query=query, project_id=None, limit=limit)

    return await _search_graph_service_projects(
        graph_service,
        query=query,
        project_ids=allowed_project_ids,
        limit=limit,
    )


async def _tenant_search_project_ids(
    tenant_id: str,
    current_user: User,
    db: AsyncSession,
) -> list[str]:
    if getattr(current_user, "is_superuser", False):
        result = await db.execute(
            refresh_select_statement(
                select(Project.id).where(Project.tenant_id == tenant_id).order_by(Project.id.asc())
            )
        )
        return [str(project_id) for project_id in result.scalars().all()]

    _is_superuser, allowed_project_ids = await _graph_project_scope(
        None,
        current_user,
        db,
        tenant_id=tenant_id,
    )
    return allowed_project_ids


async def _search_graph_service_projects(
    graph_service: GraphServicePort,
    *,
    query: str,
    project_ids: list[str],
    limit: int,
) -> list[Any]:
    if not project_ids:
        return []

    results: list[Any] = []
    seen_keys: set[tuple[str, str]] = set()
    for allowed_project_id in project_ids:
        project_results = await graph_service.search(
            query=query,
            project_id=allowed_project_id,
            limit=limit,
        )
        for item in project_results:
            item_type = str(item.get("type", ""))
            item_uuid = str(item.get("uuid", item.get("memory_id", item.get("name", ""))))
            key = (item_type, item_uuid)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            results.append(item)
            if len(results) >= limit:
                return results

    return results


def _parse_optional_datetime(value: str | None, field: str) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        if field == "since":
            raise HTTPException(
                status_code=400, detail=_("Invalid 'since' datetime format")
            ) from None
        raise HTTPException(status_code=400, detail=_("Invalid 'until' datetime format")) from None


def _empty_temporal_response(since: str | None, until: str | None) -> dict[str, Any]:
    return {
        "results": [],
        "total": 0,
        "search_type": "temporal",
        "time_range": {
            "since": since,
            "until": until,
        },
    }


def _empty_faceted_response(limit: int, offset: int) -> dict[str, Any]:
    return {
        "results": [],
        "facets": {"entity_types": {}, "total": 0},
        "total": 0,
        "limit": limit,
        "offset": offset,
        "search_type": "faceted",
    }


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
    db: AsyncSession = Depends(get_db),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
) -> dict[str, Any]:
    """
    Perform advanced search with configurable strategy and reranking.

    Uses NativeGraphAdapter's hybrid search (vector + keyword + RRF fusion).
    """
    logger.info(f"search_advanced called: query='{query}', project_id='{project_id}'")
    try:
        if not graph_service:
            raise HTTPException(status_code=503, detail=_("Graph service not available"))

        # Use NativeGraphAdapter's search method
        results = await _search_graph_service_for_scope(
            graph_service,
            query=query,
            tenant_id=tenant_id,
            project_id=project_id,
            limit=limit,
            current_user=current_user,
            db=db,
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
        raise HTTPException(status_code=500, detail=_("Advanced search failed")) from e


@router.post("/graph-traversal")
async def search_by_graph_traversal(
    start_entity_uuid: str = Body(..., description="Starting entity UUID"),
    max_depth: int = Body(2, ge=1, le=5, description="Maximum traversal depth"),
    relationship_types: list[str] | None = Body(None, description="Relationship types to follow"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    tenant_id: str | None = Body(None, description="Tenant filter"),
    project_id: str | None = Body(None, description="Project filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Search by traversing the knowledge graph from a starting entity.

    This performs graph traversal to find related entities, episodes, and communities.
    Useful for exploring connections and discovering related content.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))

        start_project_id = await graph_store.get_entity_project_id(start_entity_uuid)
        if start_project_id is None:
            raise HTTPException(status_code=404, detail=_("Entity not found"))

        effective_project_id = project_id or start_project_id
        if project_id:
            await _graph_project_scope(project_id, current_user, db, tenant_id=tenant_id)
            if start_project_id != project_id:
                return {"results": [], "total": 0, "search_type": "graph_traversal"}
        else:
            await _graph_project_scope(effective_project_id, current_user, db, tenant_id=tenant_id)

        rows = await graph_store.graph_traversal_search(
            start_entity_uuid=start_entity_uuid,
            max_depth=max_depth,
            relationship_types=relationship_types,
            limit=limit,
            project_id=effective_project_id,
        )

        items = []
        for row in rows:
            props = {key: _sanitize_graph_value(value) for key, value in row["props"].items()}
            labels = row.get("labels", [])
            entity_type = _entity_type_from_props_or_labels(props, labels)
            items.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "type": entity_type,
                    "summary": props.get("summary", ""),
                    "content": props.get("content", ""),
                    "created_at": props.get("created_at"),
                    "metadata": {
                        "uuid": props.get("uuid", ""),
                        "name": props.get("name", ""),
                        "type": entity_type,
                        "created_at": props.get("created_at"),
                    },
                }
            )

        return {
            "results": items,
            "total": len(items),
            "search_type": "graph_traversal",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Graph traversal search failed: {e}")
        raise HTTPException(status_code=500, detail=_("Graph traversal search failed")) from e


@router.post("/community")
async def search_by_community(
    community_uuid: str = Body(..., description="Community UUID"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    include_episodes: bool = Body(True, description="Include episodes in results"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Search within a community for related content.

    This finds all entities and optionally episodes within a specific community.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))

        community_project_id = await graph_store.get_community_project_id(community_uuid)
        if community_project_id is None:
            raise HTTPException(status_code=404, detail=_("Community not found"))
        await _ensure_graph_project_access(community_project_id, current_user, db)

        items = await graph_store.community_search(
            community_uuid=community_uuid,
            project_id=community_project_id,
            include_episodes=include_episodes,
            limit=limit,
        )

        return {
            "results": items[:limit],
            "total": len(items),
            "search_type": "community",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Community search failed: {e}")
        raise HTTPException(status_code=500, detail=_("Community search failed")) from e


@router.post("/temporal")
async def search_temporal(
    query: str = Body(..., description="Search query"),
    since: str | None = Body(None, description="Start of time range (ISO format)"),
    until: str | None = Body(None, description="End of time range (ISO format)"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    tenant_id: str | None = Body(None, description="Tenant filter"),
    project_id: str | None = Body(None, description="Project filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Search within a temporal window.

    Performs semantic search restricted to a specific time range.
    Useful for finding memories from specific periods.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        parsed_since = _parse_optional_datetime(since, "since")
        parsed_until = _parse_optional_datetime(until, "until")

        # Resolve scope + access (empty scope => no accessible projects).
        is_superuser, allowed_project_ids = await _graph_project_scope(
            project_id, current_user, db, tenant_id=tenant_id
        )
        if not is_superuser and not allowed_project_ids:
            return _empty_temporal_response(since, until)

        scope_project_id = project_id
        scope_project_ids: list[str] | None = None
        if not project_id and not is_superuser:
            scope_project_ids = allowed_project_ids

        items = await graph_store.temporal_search(
            query=query.strip() or None,
            since_iso=parsed_since.isoformat() if parsed_since else None,
            until_iso=parsed_until.isoformat() if parsed_until else None,
            limit=limit,
            project_id=scope_project_id,
            tenant_id=tenant_id,
            project_ids=scope_project_ids,
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
        raise HTTPException(status_code=500, detail=_("Temporal search failed")) from e


@router.post("/faceted")
async def search_with_facets(
    query: str = Body(..., description="Search query"),
    entity_types: list[str] | None = Body(None, description="Filter by entity types"),
    tags: list[str] | None = Body(None, description="Filter by tags"),
    since: str | None = Body(None, description="Filter by creation date (ISO format)"),
    limit: int = Body(50, ge=1, le=200, description="Maximum results"),
    offset: int = Body(0, ge=0, description="Pagination offset"),
    tenant_id: str | None = Body(None, description="Tenant filter"),
    project_id: str | None = Body(None, description="Project filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Search with faceted filtering.

    Performs semantic search with additional filters and returns facet counts
    for UI filtering controls.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        parsed_since = _parse_optional_datetime(since, "since")

        # Resolve scope + access (empty scope => no accessible projects).
        is_superuser, allowed_project_ids = await _graph_project_scope(
            project_id, current_user, db, tenant_id=tenant_id
        )
        if not is_superuser and not allowed_project_ids:
            return _empty_faceted_response(limit, offset)

        scope_project_id = project_id
        scope_project_ids: list[str] | None = None
        if not project_id and not is_superuser:
            scope_project_ids = allowed_project_ids

        rows = await graph_store.faceted_search(
            query=query.strip() or None,
            entity_types=entity_types,
            tags=tags,
            since_iso=parsed_since.isoformat() if parsed_since else None,
            limit=limit,
            offset=offset,
            project_id=scope_project_id,
            tenant_id=tenant_id,
            project_ids=scope_project_ids,
        )

        items = []
        for row in rows:
            labels = row.pop("labels", [])
            props = row
            entity_type = _entity_type_from_props_or_labels(props, labels)
            items.append(
                {
                    "uuid": props.get("uuid", ""),
                    "name": props.get("name", ""),
                    "type": entity_type,
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
        entity_type_counts: dict[str, int] = {}
        facets: dict[str, Any] = {"entity_types": entity_type_counts, "total": len(items)}

        for item in items:
            et = item.get("entity_type", "Entity")
            entity_type_counts[et] = entity_type_counts.get(et, 0) + 1

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
        raise HTTPException(status_code=500, detail=_("Faceted search failed")) from e


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
    db: AsyncSession = Depends(get_db),
    graph_service: GraphServicePort | None = Depends(get_graph_service),
    retrieval_store: RetrievalStorePort | None = Depends(get_retrieval_store),
) -> dict[str, Any]:
    """
    Search memories using hybrid search.

    This endpoint consolidates search functionality.
    Supports semantic search, keyword search, and graph traversal.
    """
    try:
        query = params.get("query", "")
        limit = params.get("limit", 10)
        project_id = params.get("project_id")

        if not query:
            raise HTTPException(status_code=400, detail=_("Query is required"))

        if not graph_service and not retrieval_store:
            raise HTTPException(status_code=503, detail=_("Graph service not available"))

        results: list[Any] = []
        if retrieval_store is not None and project_id:
            retrieval_results = await retrieval_store.hybrid_search(
                query=query,
                project_id=project_id,
                limit=limit,
            )
            results.extend(
                {
                    "uuid": item.id,
                    "name": item.metadata.get("title") or item.source_id or item.id,
                    "content": item.content,
                    "type": "episode",
                    "score": item.score,
                    "created_at": item.created_at,
                    "source": item.source_type,
                    "source_description": item.category,
                }
                for item in retrieval_results
            )

        if graph_service is not None and len(results) < limit:
            graph_results = await _search_graph_service_for_scope(
                graph_service,
                query=query,
                tenant_id=None,
                project_id=project_id,
                limit=limit - len(results),
                current_user=current_user,
                db=db,
            )
            results.extend(graph_results)

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
        raise HTTPException(status_code=500, detail=_("Search failed")) from e
