"""Data export and management API routes."""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_db,
    get_graphiti_client,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import (
    has_global_admin_access,
    require_tenant_access,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["data"])


def _records(result: Any) -> Sequence[Any]:
    try:
        recs = getattr(result, "records", None)
        if isinstance(recs, (list, tuple)):
            return cast(Sequence[Any], recs)
        if isinstance(result, (list, tuple)):
            return cast(Sequence[Any], result)
        return []
    except Exception:
        return []


def _first_value(recs: Any, key: str) -> Any:
    if not recs:
        return 0
    r0 = recs[0]
    return _extract_value(r0, key)


def _extract_value(r0: Any, key: str) -> Any:
    """Extract a value from a record by key."""
    if isinstance(r0, dict):
        return cast(dict[str, Any], r0).get(key, 0)
    if hasattr(r0, "__getitem__"):
        try:
            return r0[key]
        except Exception:
            pass
    getter = getattr(r0, "get", None)
    if callable(getter):
        try:
            typed_getter = cast(Callable[[str, Any], Any], getter)
            return typed_getter(key, 0)
        except Exception:
            return 0
    if isinstance(r0, (list, tuple)):
        seq = cast(Sequence[Any], r0)
        if seq:
            return seq[0]
    return 0


async def _is_global_admin(db: AsyncSession, current_user: User) -> bool:
    """Return whether the caller can perform cross-tenant graph operations."""
    return bool(getattr(current_user, "is_superuser", False)) or await has_global_admin_access(
        db, cast(Any, current_user)
    )


async def _default_tenant_id_for_user(db: AsyncSession, current_user: User) -> str:
    """Return the caller's default tenant from persisted membership."""
    result = await db.execute(
        refresh_select_statement(
            select(UserTenant.tenant_id).where(UserTenant.user_id == current_user.id).limit(1)
        )
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Tenant access required"),
        )
    return str(tenant_id)


async def _resolve_tenant_scope(
    requested_tenant_id: str | None,
    db: AsyncSession,
    current_user: User,
    *,
    require_admin: bool = False,
) -> str | None:
    """Resolve and authorize the tenant filter for graph data operations."""
    if await _is_global_admin(db, current_user):
        return requested_tenant_id

    tenant_id = requested_tenant_id or await _default_tenant_id_for_user(db, current_user)
    await require_tenant_access(
        db,
        cast(Any, current_user),
        tenant_id,
        require_admin=require_admin,
    )
    return tenant_id


async def _resolve_graph_export_scope(
    requested_tenant_id: str | None,
    requested_project_id: str | None,
    db: AsyncSession,
    current_user: User,
    *,
    require_admin: bool = False,
) -> tuple[str | None, str | None]:
    """Resolve tenant/project filters and authorize the requested graph data scope."""
    if requested_project_id is None:
        tenant_id = await _resolve_tenant_scope(
            requested_tenant_id,
            db,
            current_user,
            require_admin=require_admin,
        )
        return tenant_id, None

    project_result = await db.execute(
        refresh_select_statement(select(Project).where(Project.id == requested_project_id))
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Project not found"))

    project_tenant_id = str(project.tenant_id)
    if requested_tenant_id is not None and requested_tenant_id != project_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Project does not belong to tenant"),
        )

    if await _is_global_admin(db, current_user):
        return project_tenant_id, requested_project_id

    membership_query = select(UserProject).where(
        UserProject.user_id == current_user.id,
        UserProject.project_id == requested_project_id,
    )
    if require_admin:
        membership_query = membership_query.where(UserProject.role.in_(["owner", "admin"]))

    membership_result = await db.execute(refresh_select_statement(membership_query))
    if membership_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project access required"),
        )

    return project_tenant_id, requested_project_id


def _node_scope_clause(var_name: str, project_id: str | None, tenant_id: str | None) -> str:
    if project_id:
        return f"WHERE {var_name}.project_id = $project_id"
    if tenant_id:
        return f"WHERE {var_name}.tenant_id = $tenant_id"
    return ""


def _project_node_scope_condition(var_name: str, project_id: str | None) -> str:
    if project_id is None:
        return ""
    return f"""(
        {var_name}.project_id = $project_id OR EXISTS {{
            MATCH ({var_name})<-[:MENTIONS]-(project_episode:Episodic)
            WHERE project_episode.project_id = $project_id
        }}
    )"""


def _entity_scope_clause(var_name: str, project_id: str | None, tenant_id: str | None) -> str:
    project_condition = _project_node_scope_condition(var_name, project_id)
    if project_condition:
        return f"WHERE {project_condition}"
    if tenant_id:
        return f"WHERE {var_name}.tenant_id = $tenant_id"
    return ""


def _scoped_episode_query(prefix: str, project_id: str | None, tenant_id: str | None) -> str:
    scope = _node_scope_clause("e", project_id, tenant_id)
    return f"""
    MATCH (e:Episodic)
    {scope}
    {prefix}
    """


def _cleanup_body_value(body: dict[str, Any] | None, key: str, fallback: Any) -> Any:
    if body is not None and key in body:
        return body[key]
    return fallback


def _normalize_cleanup_dry_run(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=_("Invalid dry_run value"),
    )


def _normalize_cleanup_days(value: Any) -> int:
    if value is None:
        return 90
    if isinstance(value, bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("older_than_days must be a positive integer"),
        )
    if isinstance(value, int):
        days = value
    elif isinstance(value, str) and value.strip().isdecimal():
        days = int(value.strip())
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("older_than_days must be a positive integer"),
        )
    if days < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("older_than_days must be a positive integer"),
        )
    return days


async def _append_relationship_export(
    data: dict[str, Any],
    graphiti_client: Any,
    params: dict[str, str | None],
    effective_project_id: str | None,
    effective_tenant_id: str | None,
) -> None:
    rel_query = """
    MATCH (a)-[r]->(b)
    WHERE ('Entity' IN labels(a) OR 'Episodic' IN labels(a) OR 'Community' IN labels(a))
    AND ('Entity' IN labels(b) OR 'Episodic' IN labels(b) OR 'Community' IN labels(b))
    """

    if effective_project_id:
        a_scope = _project_node_scope_condition("a", effective_project_id)
        b_scope = _project_node_scope_condition("b", effective_project_id)
        rel_query += f" AND {a_scope} AND {b_scope}"
    elif effective_tenant_id:
        rel_query += " AND a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id"

    rel_query += " RETURN properties(r) as props, type(r) as rel_type, elementId(r) as edge_id"

    result = await graphiti_client.driver.execute_query(rel_query, **params)

    for r in _records(result):
        data["relationships"].append(
            {"edge_id": r["edge_id"], "type": r["rel_type"], "properties": r["props"]}
        )


# --- Endpoints ---


@router.post("/export")
async def export_data(
    tenant_id: str | None = Body(None, description="Filter by tenant ID"),
    project_id: str | None = Body(None, description="Filter by project ID"),
    include_episodes: bool = Body(True, description="Include episode data"),
    include_entities: bool = Body(True, description="Include entity data"),
    include_relationships: bool = Body(True, description="Include relationship data"),
    include_communities: bool = Body(True, description="Include community data"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Export graph data as JSON.
    """
    try:
        effective_tenant_id, effective_project_id = await _resolve_graph_export_scope(
            tenant_id,
            project_id,
            db,
            current_user,
        )
        data: dict[str, Any] = {
            "exported_at": datetime.now(UTC).isoformat(),
            "tenant_id": effective_tenant_id,
            "project_id": effective_project_id,
            "episodes": [],
            "entities": [],
            "relationships": [],
            "communities": [],
        }

        params = {"tenant_id": effective_tenant_id, "project_id": effective_project_id}

        if include_episodes:
            episode_scope = _node_scope_clause("e", effective_project_id, effective_tenant_id)
            episode_query = f"""
            MATCH (e:Episodic)
            {episode_scope}
            RETURN properties(e) as props
            ORDER BY e.created_at DESC
            """

            result = await graphiti_client.driver.execute_query(episode_query, **params)

            for r in _records(result):
                data["episodes"].append(r["props"])

        if include_entities:
            entity_scope = _entity_scope_clause("e", effective_project_id, effective_tenant_id)
            entity_query = f"""
            MATCH (e:Entity)
            {entity_scope}
            RETURN properties(e) as props, labels(e) as labels
            """

            result = await graphiti_client.driver.execute_query(entity_query, **params)

            for r in _records(result):
                props = r["props"]
                props["labels"] = r["labels"]
                data["entities"].append(props)

        if include_relationships:
            await _append_relationship_export(
                data,
                graphiti_client,
                params,
                effective_project_id,
                effective_tenant_id,
            )

        if include_communities:
            community_scope = _node_scope_clause("c", effective_project_id, effective_tenant_id)
            community_query = f"""
            MATCH (c:Community)
            {community_scope}
            RETURN properties(c) as props
            ORDER BY c.member_count DESC
            """

            result = await graphiti_client.driver.execute_query(community_query, **params)

            for r in _records(result):
                data["communities"].append(r["props"])

        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to export data")
        raise HTTPException(status_code=500, detail=_("Failed to export data")) from e


@router.get("/stats")
async def get_graph_stats(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    project_id: str | None = Query(None, description="Filter by project ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Get graph statistics.

    Returns statistics about the knowledge graph including:
    - Number of entities
    - Number of episodes
    - Number of communities
    - Number of relationships (edges)
    """
    try:
        effective_tenant_id, effective_project_id = await _resolve_graph_export_scope(
            tenant_id,
            project_id,
            db,
            current_user,
        )
        params = {"tenant_id": effective_tenant_id, "project_id": effective_project_id}

        # Entity count
        entity_scope = _entity_scope_clause("e", effective_project_id, effective_tenant_id)
        entity_query = f"""
        MATCH (e:Entity)
        {entity_scope}
        RETURN count(e) as count
        """
        entity_result = await graphiti_client.driver.execute_query(entity_query, **params)
        recs = _records(entity_result)
        entity_count = _first_value(recs, "count")

        # Episode count
        episode_scope = _node_scope_clause("e", effective_project_id, effective_tenant_id)
        episode_query = f"""
        MATCH (e:Episodic)
        {episode_scope}
        RETURN count(e) as count
        """
        episode_result = await graphiti_client.driver.execute_query(episode_query, **params)
        recs = _records(episode_result)
        episode_count = _first_value(recs, "count")

        # Community count
        community_scope = _node_scope_clause("c", effective_project_id, effective_tenant_id)
        community_query = f"""
        MATCH (c:Community)
        {community_scope}
        RETURN count(c) as count
        """
        community_result = await graphiti_client.driver.execute_query(community_query, **params)
        recs = _records(community_result)
        community_count = _first_value(recs, "count")

        # Relationship count
        rel_query = """
        MATCH (a)-[r]->(b)
        WHERE ('Entity' IN labels(a) OR 'Episodic' IN labels(a) OR 'Community' IN labels(a))
        AND ('Entity' IN labels(b) OR 'Episodic' IN labels(b) OR 'Community' IN labels(b))
        """

        if effective_project_id:
            a_scope = _project_node_scope_condition("a", effective_project_id)
            b_scope = _project_node_scope_condition("b", effective_project_id)
            rel_query += f" AND {a_scope} AND {b_scope}"
        elif effective_tenant_id:
            rel_query += " AND a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id"

        rel_query += " RETURN count(r) as count"

        rel_result = await graphiti_client.driver.execute_query(rel_query, **params)
        recs = _records(rel_result)
        rel_count = _first_value(recs, "count")

        return {
            "entities": entity_count,
            "episodes": episode_count,
            "communities": community_count,
            "relationships": rel_count,
            "total_nodes": entity_count + episode_count + community_count,
            "tenant_id": effective_tenant_id,
            "project_id": effective_project_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to get graph stats")) from e


@router.post("/cleanup")
async def cleanup_data(
    dry_run: bool | None = Query(None, description="If true, only report what would be deleted"),
    older_than_days: int | None = Query(
        None, ge=1, description="Delete data older than this many days"
    ),
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    project_id: str | None = Query(None, description="Filter by project ID"),
    body: dict[str, Any] | None = Body(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Clean up old graph data.

    This endpoint can be used to remove old episodes and their associated
    entities and relationships. Use with caution!
    """
    try:
        effective_dry_run = _normalize_cleanup_dry_run(
            _cleanup_body_value(body, "dry_run", dry_run)
        )
        effective_days = _normalize_cleanup_days(
            _cleanup_body_value(body, "older_than_days", older_than_days)
        )
        effective_tenant = _cleanup_body_value(body, "tenant_id", tenant_id)
        effective_project = _cleanup_body_value(body, "project_id", project_id)
        effective_tenant, effective_project = await _resolve_graph_export_scope(
            effective_tenant,
            effective_project,
            db,
            current_user,
            require_admin=not effective_dry_run,
        )

        cutoff_date = datetime.now(UTC) - timedelta(days=int(effective_days))

        count_query = _scoped_episode_query(
            """
        WHERE e.created_at < datetime($cutoff_date)
        RETURN count(e) as count
        """,
            effective_project,
            effective_tenant,
        )
        result = await graphiti_client.driver.execute_query(
            count_query,
            tenant_id=effective_tenant,
            project_id=effective_project,
            cutoff_date=cutoff_date.isoformat(),
        )
        recs = _records(result)
        count = _first_value(recs, "count")

        if effective_dry_run:
            return {
                "dry_run": True,
                "would_delete": count,
                "cutoff_date": cutoff_date.isoformat(),
                "tenant_id": effective_tenant,
                "project_id": effective_project,
                "message": f"Would delete {count} episodes older than {effective_days} days",
            }
        else:
            # Actually delete (DETACH DELETE removes nodes and their relationships)
            delete_query = _scoped_episode_query(
                """
            WHERE e.created_at < datetime($cutoff_date)
            DETACH DELETE e
            RETURN count(e) as deleted
            """,
                effective_project,
                effective_tenant,
            )
            result = await graphiti_client.driver.execute_query(
                delete_query,
                tenant_id=effective_tenant,
                project_id=effective_project,
                cutoff_date=cutoff_date.isoformat(),
            )
            recs = _records(result)
            deleted = _first_value(recs, "deleted")

            logger.warning(
                "Deleted %s episodes older than %s days for tenant: %s project: %s",
                deleted,
                effective_days,
                effective_tenant,
                effective_project,
            )

            return {
                "dry_run": False,
                "deleted": deleted,
                "cutoff_date": cutoff_date.isoformat(),
                "tenant_id": effective_tenant,
                "project_id": effective_project,
                "message": f"Deleted {deleted} episodes older than {effective_days} days",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cleanup data: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to cleanup data")) from e
