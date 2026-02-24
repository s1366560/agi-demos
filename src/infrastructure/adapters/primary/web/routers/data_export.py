"""Data export and management API routes."""

import logging
from datetime import UTC, datetime, timedelta
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graphiti_client,
)
from src.infrastructure.adapters.secondary.persistence.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["data"])


def _records(result: Any) -> Sequence[Any]:
    try:
        recs = getattr(result, "records", None)
        if isinstance(recs, (list, tuple)):
            return recs
        if isinstance(result, (list, tuple)):
            return result
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
        return r0.get(key, 0)
    if hasattr(r0, "__getitem__"):
        try:
            return r0[key]
        except Exception:
            pass
    if hasattr(r0, "get"):
        try:
            return r0.get(key, 0)
        except Exception:
            return 0
    if isinstance(r0, (list, tuple)) and len(r0) > 0:
        return r0[0]
    return 0


# --- Endpoints ---


@router.post("/export")
async def export_data(
    tenant_id: str | None = Body(None, description="Filter by tenant ID"),
    include_episodes: bool = Body(True, description="Include episode data"),
    include_entities: bool = Body(True, description="Include entity data"),
    include_relationships: bool = Body(True, description="Include relationship data"),
    include_communities: bool = Body(True, description="Include community data"),
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Export graph data as JSON.
    """
    try:
        data = {
            "exported_at": datetime.now(UTC).isoformat(),
            "tenant_id": tenant_id,
            "episodes": [],
            "entities": [],
            "relationships": [],
            "communities": [],
        }

        tenant_filter = "{tenant_id: $tenant_id}" if tenant_id else ""

        if include_episodes:
            episode_query = f"""
            MATCH (e:Episodic {tenant_filter})
            RETURN properties(e) as props
            ORDER BY e.created_at DESC
            """

            result = await graphiti_client.driver.execute_query(episode_query, tenant_id=tenant_id)

            for r in _records(result):
                data["episodes"].append(r["props"])

        if include_entities:
            entity_query = f"""
            MATCH (e:Entity {tenant_filter})
            RETURN properties(e) as props, labels(e) as labels
            """

            result = await graphiti_client.driver.execute_query(entity_query, tenant_id=tenant_id)

            for r in _records(result):
                props = r["props"]
                props["labels"] = r["labels"]
                data["entities"].append(props)

        if include_relationships:
            rel_query = """
            MATCH (a)-[r]->(b)
            WHERE ('Entity' IN labels(a) OR 'Episodic' IN labels(a) OR 'Community' IN labels(a))
            AND ('Entity' IN labels(b) OR 'Episodic' IN labels(b) OR 'Community' IN labels(b))
            """

            if tenant_id:
                rel_query += " AND a.tenant_id = $tenant_id"

            rel_query += (
                " RETURN properties(r) as props, type(r) as rel_type, elementId(r) as edge_id"
            )

            result = await graphiti_client.driver.execute_query(rel_query, tenant_id=tenant_id)

            for r in _records(result):
                data["relationships"].append(
                    {"edge_id": r["edge_id"], "type": r["rel_type"], "properties": r["props"]}
                )

        if include_communities:
            community_query = f"""
            MATCH (c:Community {tenant_filter})
            RETURN properties(c) as props
            ORDER BY c.member_count DESC
            """

            result = await graphiti_client.driver.execute_query(
                community_query, tenant_id=tenant_id
            )

            for r in _records(result):
                data["communities"].append(r["props"])

        return data

    except Exception as e:
        logger.error(f"Failed to export data: {e}")
        return {
            "exported_at": datetime.now(UTC).isoformat(),
            "tenant_id": tenant_id,
            "episodes": [],
            "entities": [],
            "relationships": [],
            "communities": [],
        }


@router.get("/stats")
async def get_graph_stats(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    current_user: User = Depends(get_current_user),
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
        tenant_filter = "{tenant_id: $tenant_id}" if tenant_id else ""

        # Entity count
        entity_query = f"""
        MATCH (e:Entity {tenant_filter})
        RETURN count(e) as count
        """
        entity_result = await graphiti_client.driver.execute_query(
            entity_query, tenant_id=tenant_id
        )
        recs = _records(entity_result)
        entity_count = _first_value(recs, "count")

        # Episode count
        episode_query = f"""
        MATCH (e:Episodic {tenant_filter})
        RETURN count(e) as count
        """
        episode_result = await graphiti_client.driver.execute_query(
            episode_query, tenant_id=tenant_id
        )
        recs = _records(episode_result)
        episode_count = _first_value(recs, "count")

        # Community count
        community_query = f"""
        MATCH (c:Community {tenant_filter})
        RETURN count(c) as count
        """
        community_result = await graphiti_client.driver.execute_query(
            community_query, tenant_id=tenant_id
        )
        recs = _records(community_result)
        community_count = _first_value(recs, "count")

        # Relationship count
        rel_query = """
        MATCH (a)-[r]->(b)
        WHERE ('Entity' IN labels(a) OR 'Episodic' IN labels(a) OR 'Community' IN labels(a))
        AND ('Entity' IN labels(b) OR 'Episodic' IN labels(b) OR 'Community' IN labels(b))
        """

        if tenant_id:
            rel_query += " AND a.tenant_id = $tenant_id"

        rel_query += " RETURN count(r) as count"

        rel_result = await graphiti_client.driver.execute_query(rel_query, tenant_id=tenant_id)
        recs = _records(rel_result)
        rel_count = _first_value(recs, "count")

        return {
            "entities": entity_count,
            "episodes": episode_count,
            "communities": community_count,
            "relationships": rel_count,
            "total_nodes": entity_count + episode_count + community_count,
            "tenant_id": tenant_id,
        }

    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/cleanup")
async def cleanup_data(
    dry_run: bool | None = Query(None, description="If true, only report what would be deleted"),
    older_than_days: int | None = Query(
        None, ge=1, description="Delete data older than this many days"
    ),
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    body: dict[str, Any] | None = Body(None),
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Clean up old graph data.

    This endpoint can be used to remove old episodes and their associated
    entities and relationships. Use with caution!
    """
    try:
        # Allow body to override query defaults
        effective_dry_run = body.get("dry_run") if body and "dry_run" in body else dry_run
        if effective_dry_run is None:
            effective_dry_run = True
        effective_days = (
            body.get("older_than_days") if body and "older_than_days" in body else older_than_days
        )
        if effective_days is None:
            effective_days = 90
        effective_tenant = body.get("tenant_id") if body and "tenant_id" in body else tenant_id

        cutoff_date = datetime.now(UTC) - timedelta(days=int(effective_days))

        # Count episodes that would be deleted
        tenant_filter = "{tenant_id: $tenant_id}" if effective_tenant else ""
        count_query = f"""
        MATCH (e:Episodic {tenant_filter})
        WHERE e.created_at < datetime($cutoff_date)
        RETURN count(e) as count
        """
        result = await graphiti_client.driver.execute_query(
            count_query,
            tenant_id=effective_tenant,
            cutoff_date=cutoff_date.isoformat(),
        )
        recs = _records(result)
        count = _first_value(recs, "count")

        if effective_dry_run:
            return {
                "dry_run": True,
                "would_delete": count,
                "cutoff_date": cutoff_date.isoformat(),
                "message": f"Would delete {count} episodes older than {effective_days} days",
            }
        else:
            # Actually delete (DETACH DELETE removes nodes and their relationships)
            delete_query = f"""
            MATCH (e:Episodic {tenant_filter})
            WHERE e.created_at < datetime($cutoff_date)
            DETACH DELETE e
            RETURN count(e) as deleted
            """
            result = await graphiti_client.driver.execute_query(
                delete_query,
                tenant_id=effective_tenant,
                cutoff_date=cutoff_date.isoformat(),
            )
            recs = _records(result)
            deleted = _first_value(recs, "deleted")

            logger.warning(
                f"Deleted {deleted} episodes older than {effective_days} days for tenant: {effective_tenant}"
            )

            return {
                "dry_run": False,
                "deleted": deleted,
                "cutoff_date": cutoff_date.isoformat(),
                "message": f"Deleted {deleted} episodes older than {effective_days} days",
            }

    except Exception as e:
        logger.error(f"Failed to cleanup data: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
