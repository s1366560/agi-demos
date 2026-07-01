"""Knowledge Graph API routes.

This router provides endpoints for accessing and manipulating the knowledge graph structure,
including communities, entities, and graph visualizations. Search functionality has been
moved to enhanced_search.py to avoid duplication.
"""

import logging
from collections.abc import Iterable
from datetime import UTC
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graph_store,
    get_workflow_engine,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserProject
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])
_BASE_ENTITY_LABELS = {"Entity", "Node", "BaseEntity"}


async def _graph_project_scope(
    project_id: str | None,
    current_user: User,
    db: AsyncSession,
    tenant_id: str | None = None,
) -> tuple[bool, list[str]]:
    """Return whether the caller is global admin plus the allowed project IDs."""
    if project_id and tenant_id:
        project_result = await db.execute(
            refresh_select_statement(select(Project.tenant_id).where(Project.id == project_id))
        )
        project_tenant_id = project_result.scalar_one_or_none()
        if project_tenant_id is None:
            raise HTTPException(status_code=404, detail=_("Project not found"))
        if str(project_tenant_id) != tenant_id:
            raise HTTPException(status_code=400, detail=_("Project does not belong to tenant"))

    if getattr(current_user, "is_superuser", False):
        return True, [project_id] if project_id else []

    if project_id:
        statement = select(UserProject.id).where(
            and_(
                UserProject.user_id == current_user.id,
                UserProject.project_id == project_id,
            )
        )
        result = await db.execute(refresh_select_statement(statement))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail=_("Access denied to project"))
        return False, [project_id]

    statement = select(UserProject.project_id).where(UserProject.user_id == current_user.id)
    if tenant_id:
        statement = statement.join(Project, Project.id == UserProject.project_id).where(
            Project.tenant_id == tenant_id
        )
    result = await db.execute(refresh_select_statement(statement))
    return False, list(result.scalars().all())


async def _ensure_graph_project_access(
    project_id: str | None,
    current_user: User,
    db: AsyncSession,
) -> None:
    if getattr(current_user, "is_superuser", False):
        return

    if not project_id:
        raise HTTPException(status_code=403, detail=_("Access denied to project"))

    await _graph_project_scope(project_id, current_user, db)


def _empty_graph_elements() -> dict[str, Any]:
    return {"elements": {"nodes": [], "edges": []}}


def _rows_to_elements(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble graph-visualization rows into a cytoscape elements payload.

    Shared by ``get_graph`` and ``get_subgraph``. Each row carries source/target/
    edge props+labels (see ``GraphStorePort.get_graph_visualization`` /
    ``get_subgraph``).
    """
    nodes_map: dict[str, dict[str, Any]] = {}
    edges_list: list[dict[str, Any]] = []

    for r in rows:
        s_id = r.get("source_id")
        if s_id:
            s_props = _sanitize_graph_properties(
                r.get("source_props") or {}, excluded_keys={"name_embedding"}
            )
            if s_id not in nodes_map:
                nodes_map[s_id] = {
                    "data": {
                        "id": s_id,
                        "label": _graph_node_label(s_props, r.get("source_labels") or []),
                        "name": s_props.get("name", "Unknown"),
                        **s_props,
                    }
                }

        t_id = r.get("target_id")
        if t_id:
            t_props = _sanitize_graph_properties(
                r.get("target_props") or {}, excluded_keys={"name_embedding"}
            )
            if t_id not in nodes_map:
                nodes_map[t_id] = {
                    "data": {
                        "id": t_id,
                        "label": _graph_node_label(t_props, r.get("target_labels") or []),
                        "name": t_props.get("name", "Unknown"),
                        **t_props,
                    }
                }

            e_id = r.get("edge_id")
            if e_id:
                e_props = _sanitize_graph_properties(
                    r.get("edge_props") or {}, excluded_keys={"fact_embedding"}
                )
                edges_list.append(
                    {
                        "data": {
                            "id": e_id,
                            "source": s_id,
                            "target": t_id,
                            "label": r.get("edge_type"),
                            **e_props,
                        }
                    }
                )

    return {"elements": {"nodes": list(nodes_map.values()), "edges": edges_list}}


def _serialize_datetime(value: Any) -> str | None:
    """Convert Neo4j DateTime to ISO string for JSON serialization."""
    if value is None:
        return None
    # Neo4j DateTime has isoformat() method
    if hasattr(value, "isoformat"):
        return cast(str | None, value.isoformat())
    # Fallback to string conversion
    return str(value) if value else None


def _sanitize_graph_value(value: Any) -> Any:
    """Convert Neo4j driver values into JSON-serializable response values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        raw_dict = cast(dict[str, Any], value)
        return {key: _sanitize_graph_value(nested_value) for key, nested_value in raw_dict.items()}

    if isinstance(value, (list, tuple, set)):
        raw_items = cast(Iterable[Any], value)
        return [_sanitize_graph_value(item) for item in raw_items]

    if hasattr(value, "isoformat"):
        return cast(str, value.isoformat())

    return str(value)


def _sanitize_graph_properties(
    props: dict[str, Any] | None, excluded_keys: set[str]
) -> dict[str, Any]:
    if not props:
        return {}

    return {
        key: _sanitize_graph_value(value)
        for key, value in props.items()
        if key not in excluded_keys
    }


def _entity_type_from_props_or_labels(props: dict[str, Any], labels: list[str]) -> str:
    entity_type = props.get("entity_type")
    if isinstance(entity_type, str) and entity_type:
        return entity_type
    return next((label for label in labels if label not in _BASE_ENTITY_LABELS), "Entity")


def _graph_node_label(props: dict[str, Any], labels: list[str]) -> str:
    if "Entity" in labels:
        return _entity_type_from_props_or_labels(props, labels)
    return next((label for label in labels if label != "Node"), labels[0] if labels else "Entity")


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
    elements: dict[str, Any]


class SubgraphRequest(BaseModel):
    node_uuids: list[str]
    include_neighbors: bool = True
    limit: int = 100
    tenant_id: str | None = None
    project_id: str | None = None


# --- Graph Structure Endpoints ---


@router.get("/communities/")
async def list_communities(
    tenant_id: str | None = None,
    project_id: str | None = None,
    min_members: int | None = Query(None, description="Minimum member count"),
    limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    List communities in the knowledge graph with filtering and pagination.

    Note: Communities are now associated with projects via project_id (which equals group_id).
    If project_id is provided, filters by that project. Otherwise, returns all communities.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        is_superuser, allowed_project_ids = await _graph_project_scope(
            project_id, current_user, db, tenant_id=tenant_id
        )
        if not is_superuser and not allowed_project_ids:
            return {"communities": [], "total": 0, "limit": limit, "offset": offset}

        page = await graph_store.list_communities(
            min_members=min_members,
            limit=limit,
            offset=offset,
            project_id=project_id,
            tenant_id=tenant_id if (tenant_id and is_superuser) else None,
            project_ids=allowed_project_ids if (not project_id and not is_superuser) else None,
            is_superuser=is_superuser,
        )
        communities = [
            {
                **c,
                "formed_at": _serialize_datetime(c.get("formed_at")),
                "created_at": _serialize_datetime(c.get("created_at")),
            }
            for c in page["communities"]
        ]
        return {
            "communities": communities,
            "total": page["total"],
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list communities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=_("Failed to list communities")) from e


@router.get("/entities/")
async def list_entities(
    tenant_id: str | None = None,
    project_id: str | None = None,
    entity_type: str | None = Query(None, description="Filter by entity type"),
    limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """List entities in the knowledge graph with filtering and pagination."""
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        is_superuser, allowed_project_ids = await _graph_project_scope(
            project_id, current_user, db, tenant_id=tenant_id
        )
        if not is_superuser and not allowed_project_ids:
            return {"entities": [], "total": 0, "limit": limit, "offset": offset}

        page = await graph_store.list_entities(
            entity_type=entity_type,
            limit=limit,
            offset=offset,
            project_id=project_id,
            tenant_id=tenant_id if (tenant_id and is_superuser) else None,
            project_ids=allowed_project_ids if (not project_id and not is_superuser) else None,
            is_superuser=is_superuser,
        )
        entities = [
            {**e, "created_at": _serialize_datetime(e.get("created_at"))}
            for e in page["entities"]
        ]
        return {"entities": entities, "total": page["total"], "limit": limit, "offset": offset}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list entities: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to list entities")) from e


@router.get("/entities/types")
async def get_entity_types(
    tenant_id: str | None = None,
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Get all available entity types with their counts.

    Useful for populating filter dropdowns with dynamic entity types.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        is_superuser, allowed_project_ids = await _graph_project_scope(
            project_id, current_user, db, tenant_id=tenant_id
        )
        if not is_superuser and not allowed_project_ids:
            return {"entity_types": [], "total": 0}

        entity_types = await graph_store.get_entity_types(
            project_id=project_id,
            tenant_id=tenant_id if (tenant_id and is_superuser) else None,
            project_ids=allowed_project_ids if (not project_id and not is_superuser) else None,
            is_superuser=is_superuser,
        )
        return {"entity_types": entity_types, "total": len(entity_types)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get entity types: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to get entity types")) from e


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Get entity details by UUID.

    Args:
        entity_id: Entity UUID

    Returns:
        Entity details with properties
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        props = await graph_store.get_entity(entity_id)
        if not props:
            raise HTTPException(status_code=404, detail=_("Entity not found"))

        await _ensure_graph_project_access(props.get("project_id"), current_user, db)

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
                    "labels",
                ]
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get entity {entity_id}: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to get entity")) from e


@router.get("/entities/{entity_id}/relationships")
async def get_entity_relationships(
    entity_id: str,
    relationship_type: str | None = Query(None, description="Filter by relationship type"),
    limit: int = Query(50, ge=1, le=200, description="Maximum relationships to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Get relationships for an entity.

    Returns both outgoing and incoming relationships for the specified entity.
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        entity_props = await graph_store.get_entity(entity_id)
        if not entity_props:
            raise HTTPException(status_code=404, detail=_("Entity not found"))

        entity_project_id = entity_props.get("project_id")
        await _ensure_graph_project_access(entity_project_id, current_user, db)

        page = await graph_store.get_entity_relationships(
            entity_id,
            relationship_type=relationship_type,
            limit=limit,
            project_id=entity_project_id,
            is_superuser=getattr(current_user, "is_superuser", False),
        )
        relationships = []
        for r in page["relationships"]:
            related_props = r.get("related_props", {})
            related_labels = r.get("related_labels", [])
            related_type = _entity_type_from_props_or_labels(related_props, related_labels)
            relationships.append(
                {
                    "edge_id": r["edge_id"],
                    "relation_type": r["relation_type"],
                    "direction": r["direction"],
                    "fact": r.get("fact", ""),
                    "score": r.get("score", 0.0),
                    "created_at": _serialize_datetime(r.get("created_at")),
                    "updated_at": _serialize_datetime(r.get("updated_at")),
                    "related_entity": {
                        "uuid": related_props.get("uuid", ""),
                        "name": related_props.get("name", ""),
                        "entity_type": related_type,
                        "summary": related_props.get("summary", ""),
                        "created_at": _serialize_datetime(related_props.get("created_at")),
                    },
                }
            )
        return {"relationships": relationships, "total": page["total"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get relationships for entity {entity_id}: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to get entity relationships")) from e


@router.get("/memory/graph")
async def get_graph(
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
    since: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """Get graph data for visualization."""
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        is_superuser, allowed_project_ids = await _graph_project_scope(
            project_id, current_user, db, tenant_id=tenant_id
        )
        if not is_superuser and not allowed_project_ids:
            return _empty_graph_elements()

        rows = await graph_store.get_graph_visualization(
            limit=limit,
            since=since,
            project_id=project_id,
            tenant_id=tenant_id if (tenant_id and is_superuser) else None,
            project_ids=allowed_project_ids if (not project_id and not is_superuser) else None,
            is_superuser=is_superuser,
        )
        return _rows_to_elements(rows)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get graph: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to get graph")) from e


@router.post("/memory/graph/subgraph")
async def get_subgraph(
    params: SubgraphRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """Get subgraph for specific nodes."""
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        project_id = params.project_id
        is_superuser, allowed_project_ids = await _graph_project_scope(
            project_id,
            current_user,
            db,
            tenant_id=params.tenant_id,
        )
        if not is_superuser and not allowed_project_ids:
            return _empty_graph_elements()

        rows = await graph_store.get_subgraph(
            node_uuids=params.node_uuids,
            include_neighbors=params.include_neighbors,
            limit=params.limit,
            project_id=project_id,
            tenant_id=params.tenant_id,
            project_ids=allowed_project_ids,
            is_superuser=is_superuser,
        )
        return _rows_to_elements(rows)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get subgraph: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to get subgraph")) from e


# --- Community Detail Endpoints ---


@router.get("/communities/{community_id}")
async def get_community(
    community_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Get community details by UUID.

    Args:
        community_id: Community UUID

    Returns:
        Community details with properties
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        props = await graph_store.get_community(community_id)
        if not props:
            raise HTTPException(status_code=404, detail=_("Community not found"))

        await _ensure_graph_project_access(props.get("project_id"), current_user, db)

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
        raise HTTPException(status_code=500, detail=_("Failed to get community")) from e


@router.get("/communities/{community_id}/members")
async def get_community_members(
    community_id: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum members to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Get members (entities) of a community.

    Args:
        community_id: Community UUID
        limit: Maximum members to return

    Returns:
        List of community members with their details
    """
    try:
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))
        community_props = await graph_store.get_community(community_id)
        if not community_props:
            raise HTTPException(status_code=404, detail=_("Community not found"))

        community_project_id = community_props.get("project_id")
        await _ensure_graph_project_access(community_project_id, current_user, db)

        page = await graph_store.get_community_members(
            community_id,
            limit=limit,
            project_id=community_project_id,
            is_superuser=getattr(current_user, "is_superuser", False),
        )
        members = [
            {**m, "created_at": _serialize_datetime(m.get("created_at"))}
            for m in page["members"]
        ]
        return {"members": members, "total": page["total"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get members for community {community_id}: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to get community members")) from e


@router.post("/communities/rebuild")
async def rebuild_communities(
    background: bool = Query(False, description="Run in background mode"),
    project_id: str | None = Query(None, description="Project ID to rebuild communities for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> dict[str, Any]:
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
    await _ensure_graph_project_access(target_project_id, current_user, db)

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
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend not available"))

        try:
            result = await graph_store.rebuild_communities(target_project_id)
            return {
                "status": "success",
                "message": "Communities rebuilt successfully",
                "communities_count": result["communities_count"],
                "entities_processed": result["entities_processed"],
            }
        except Exception as e:
            logger.exception("Failed to rebuild communities")
            raise HTTPException(status_code=500, detail=_("Failed to rebuild communities")) from e
