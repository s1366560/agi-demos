"""Graph maintenance and optimization API routes."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graphiti_client,
    get_neo4j_client,
    get_workflow_engine,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])


# --- Endpoints ---


@router.post("/refresh/incremental")
async def incremental_refresh(
    episode_uuids: list[str] | None = Body(None, description="Episode UUIDs to reprocess"),
    rebuild_communities: bool = Body(False, description="Whether to rebuild communities"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> dict[str, Any]:
    """
    Perform incremental refresh of the knowledge graph.

    This method updates the graph by reprocessing specific episodes
    and optionally rebuilding communities. More efficient than full rebuild.

    If no episode_uuids provided, will refresh recent episodes from last 24 hours.
    """
    from uuid import uuid4

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    try:
        # Get group_id from project context
        group_id = getattr(current_user, "project_id", None) or "neo4j"
        tenant_id = getattr(current_user, "tenant_id", None)
        project_id = getattr(current_user, "project_id", None)
        user_id = str(current_user.id)

        # Create task payload
        task_payload = {
            "group_id": group_id,
            "episode_uuids": episode_uuids,
            "rebuild_communities": rebuild_communities,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "user_id": user_id,
        }

        # Create TaskLog record
        task_id = str(uuid4())
        async with async_session_factory() as session, session.begin():
            task_log = TaskLog(
                id=task_id,
                group_id=group_id,
                task_type="incremental_refresh",
                status="PENDING",
                payload=task_payload,
                entity_type="episode",
                created_at=datetime.now(UTC),
            )
            session.add(task_log)

        # Add task_id to payload for progress tracking
        task_payload["task_id"] = task_id

        # Start Temporal workflow
        workflow_id = f"incremental-refresh-{group_id}-{task_id[:8]}"

        await workflow_engine.start_workflow(
            workflow_name="incremental_refresh",
            workflow_id=workflow_id,
            input_data=task_payload,
            task_queue="default",
        )

        logger.info(
            f"Submitted incremental refresh task {task_id} "
            f"(project: {project_id}, workflow_id={workflow_id})"
        )

        return {
            "status": "submitted",
            "message": "Incremental refresh task submitted to Temporal",
            "task_id": task_id,
            "workflow_id": workflow_id,
            "episodes_to_process": len(episode_uuids) if episode_uuids else "recent episodes",
            "task_url": f"/api/v1/tasks/{task_id}",
        }

    except Exception as e:
        logger.error(f"Failed to submit incremental refresh: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/deduplicate")
async def deduplicate_entities(
    similarity_threshold: float = Body(0.9, ge=0.0, le=1.0, description="Similarity threshold"),
    dry_run: bool = Body(True, description="If true, only report duplicates without merging"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> dict[str, Any]:
    """
    Find and optionally merge duplicate entities.

    Uses name similarity to detect potential duplicates.
    Set dry_run=false to actually merge duplicates.
    """
    from uuid import uuid4

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    try:
        group_id = getattr(current_user, "project_id", None) or "neo4j"
        project_id = getattr(current_user, "project_id", None)

        if dry_run:
            # Quick dry-run check using exact name match
            query = """
            MATCH (e:Entity)
            WITH e.name as name, collect(e) as entities
            WHERE size(entities) > 1
            RETURN name, entities
            LIMIT 100
            """

            result = await neo4j_client.execute_query(query)

            duplicates = []
            for r in result.records:
                name = r["name"]
                entities = r["entities"]
                duplicates.append(
                    {
                        "name": name,
                        "count": len(entities),
                        "uuids": [e.get("uuid", "") for e in entities],
                    }
                )

            return {
                "dry_run": True,
                "duplicates_found": len(duplicates),
                "duplicate_groups": duplicates,
                "message": f"Found {len(duplicates)} potential duplicate groups (exact name match)",
            }
        else:
            # Create task payload
            task_payload = {
                "group_id": group_id,
                "similarity_threshold": similarity_threshold,
                "dry_run": dry_run,
                "project_id": project_id,
            }

            # Create TaskLog record
            task_id = str(uuid4())
            async with async_session_factory() as session, session.begin():
                task_log = TaskLog(
                    id=task_id,
                    group_id=group_id,
                    task_type="deduplicate_entities",
                    status="PENDING",
                    payload=task_payload,
                    entity_type="entity",
                    created_at=datetime.now(UTC),
                )
                session.add(task_log)

            # Add task_id to payload for progress tracking
            task_payload["task_id"] = task_id

            # Start Temporal workflow
            workflow_id = f"deduplicate-entities-{group_id}-{task_id[:8]}"

            await workflow_engine.start_workflow(
                workflow_name="deduplicate_entities",
                workflow_id=workflow_id,
                input_data=task_payload,
                task_queue="default",
            )

            logger.info(
                f"Submitted deduplication task {task_id} "
                f"(project: {project_id}, workflow_id={workflow_id})"
            )

            return {
                "status": "submitted",
                "message": "Deduplication task submitted to Temporal",
                "task_id": task_id,
                "workflow_id": workflow_id,
                "dry_run": dry_run,
                "task_url": f"/api/v1/tasks/{task_id}",
            }

    except Exception as e:
        logger.error(f"Entity deduplication failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/invalidate-edges")
async def invalidate_stale_edges(
    days_since_update: int = Body(
        30, ge=1, description="Days since last update to consider as stale"
    ),
    dry_run: bool = Body(True, description="If true, only report without deleting"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
) -> dict[str, Any]:
    """
    Invalidate or remove stale edges that haven't been updated.

    Removes old relationships that may no longer be relevant.
    Set dry_run=false to actually delete stale edges.
    """
    try:
        cutoff_date = datetime.now(UTC) - timedelta(days=days_since_update)

        # Find stale edges (relationships with created_at timestamp)
        query = """
        MATCH (a)-[r]->(b)
        WHERE r.created_at < datetime($cutoff_date)
        RETURN type(r) as rel_type, count(r) as count
        """

        result = await neo4j_client.execute_query(query, cutoff_date=cutoff_date.isoformat())

        stale_counts = {}
        total_stale = 0
        for r in result.records:
            rel_type = r["rel_type"]
            count = r["count"]
            stale_counts[rel_type] = count
            total_stale += count

        if dry_run:
            return {
                "dry_run": True,
                "stale_edges_found": total_stale,
                "stale_by_type": stale_counts,
                "cutoff_date": cutoff_date.isoformat(),
                "message": f"Found {total_stale} stale edges older than {days_since_update} days",
            }
        else:
            # Delete stale edges
            delete_query = """
            MATCH (a)-[r]->(b)
            WHERE r.created_at < datetime($cutoff_date)
            DELETE r
            RETURN count(r) as deleted
            """

            result = await neo4j_client.execute_query(
                delete_query, cutoff_date=cutoff_date.isoformat()
            )

            deleted = result.records[0]["deleted"] if result.records else 0

            return {
                "dry_run": False,
                "deleted": deleted,
                "cutoff_date": cutoff_date.isoformat(),
                "message": f"Deleted {deleted} stale edges",
            }

    except Exception as e:
        logger.error(f"Edge invalidation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/status")
async def get_maintenance_status(
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
) -> dict[str, Any]:
    """
    Get maintenance status and recommendations.

    Returns current graph metrics and maintenance recommendations.
    """
    try:
        # Get basic graph stats
        entity_query = "MATCH (e:Entity) RETURN count(e) as count"
        entity_result = await neo4j_client.execute_query(entity_query)
        entity_count = entity_result.records[0]["count"] if entity_result.records else 0

        episode_query = "MATCH (e:Episodic) RETURN count(e) as count"
        episode_result = await neo4j_client.execute_query(episode_query)
        episode_count = episode_result.records[0]["count"] if episode_result.records else 0

        community_query = "MATCH (c:Community) RETURN count(c) as count"
        community_result = await neo4j_client.execute_query(community_query)
        community_count = community_result.records[0]["count"] if community_result.records else 0

        # Get old episodes count
        cutoff_date = datetime.now(UTC) - timedelta(days=90)
        old_query = """
        MATCH (e:Episodic)
        WHERE e.created_at < datetime($cutoff_date)
        RETURN count(e) as count
        """
        old_result = await neo4j_client.execute_query(
            old_query, cutoff_date=cutoff_date.isoformat()
        )
        old_episode_count = old_result.records[0]["count"] if old_result.records else 0

        # Generate recommendations
        recommendations = []

        if old_episode_count > 1000:
            recommendations.append(
                {
                    "type": "cleanup",
                    "priority": "medium",
                    "message": f"Consider cleaning up {old_episode_count} episodes older than 90 days",
                }
            )

        if entity_count > 10000:
            recommendations.append(
                {
                    "type": "deduplicate",
                    "priority": "low",
                    "message": "Large number of entities detected. Consider running deduplication",
                }
            )

        if community_count == 0 and episode_count > 100:
            recommendations.append(
                {
                    "type": "rebuild_communities",
                    "priority": "high",
                    "message": "No communities detected. Consider rebuilding communities",
                }
            )

        return {
            "stats": {
                "entities": entity_count,
                "episodes": episode_count,
                "communities": community_count,
                "old_episodes": old_episode_count,
            },
            "recommendations": recommendations,
            "last_checked": datetime.now(UTC).isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get maintenance status: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _run_incremental_refresh(
    group_id: str,
    tenant_id: str | None,
    project_id: str | None,
    user_id: str,
    workflow_engine: WorkflowEnginePort,
) -> dict[str, Any]:
    """Handle incremental_refresh operation for optimize_graph."""
    from uuid import uuid4

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    task_payload = {
        "group_id": group_id,
        "episode_uuids": None,
        "rebuild_communities": False,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "user_id": user_id,
    }
    task_id = str(uuid4())
    async with async_session_factory() as session, session.begin():
        task_log = TaskLog(
            id=task_id,
            group_id=group_id,
            task_type="incremental_refresh",
            status="PENDING",
            payload=task_payload,
            entity_type="episode",
            created_at=datetime.now(UTC),
        )
        session.add(task_log)
    task_payload["task_id"] = task_id
    workflow_id = f"incremental-refresh-{group_id}-{task_id[:8]}"
    await workflow_engine.start_workflow(
        workflow_name="incremental_refresh",
        workflow_id=workflow_id,
        input_data=task_payload,
        task_queue="default",
    )
    return {
        "operation": "incremental_refresh",
        "result": {"status": "success", "task_id": task_id, "workflow_id": workflow_id},
    }


async def _run_deduplicate(
    dry_run: bool,
    group_id: str,
    project_id: str | None,
    neo4j_client: Neo4jClient,
    workflow_engine: WorkflowEnginePort,
) -> dict[str, Any]:
    """Handle deduplicate operation for optimize_graph."""
    if dry_run:
        query = """
        MATCH (e:Entity)
        WITH e.name as name, collect(e) as entities
        WHERE size(entities) > 1
        RETURN name, entities
        LIMIT 100
        """
        result = await neo4j_client.execute_query(query)
        duplicates = [{"name": r["name"], "count": len(r["entities"])} for r in result.records]
        return {
            "operation": "deduplicate",
            "result": {
                "dry_run": True,
                "duplicates_found": len(duplicates),
                "message": f"Found {len(duplicates)} potential duplicate groups",
            },
        }

    from uuid import uuid4

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    task_payload = {
        "group_id": group_id,
        "similarity_threshold": 0.9,
        "dry_run": dry_run,
        "project_id": project_id,
    }
    task_id = str(uuid4())
    async with async_session_factory() as session, session.begin():
        task_log = TaskLog(
            id=task_id,
            group_id=group_id,
            task_type="deduplicate_entities",
            status="PENDING",
            payload=task_payload,
            entity_type="entity",
            created_at=datetime.now(UTC),
        )
        session.add(task_log)
    task_payload["task_id"] = task_id
    workflow_id = f"deduplicate-entities-{group_id}-{task_id[:8]}"
    await workflow_engine.start_workflow(
        workflow_name="deduplicate_entities",
        workflow_id=workflow_id,
        input_data=task_payload,
        task_queue="default",
    )
    return {
        "operation": "deduplicate",
        "result": {"status": "success", "task_id": task_id, "workflow_id": workflow_id},
    }


async def _run_invalidate_edges(
    dry_run: bool,
    neo4j_client: Neo4jClient,
) -> dict[str, Any]:
    """Handle invalidate_edges operation for optimize_graph."""
    cutoff_date = datetime.now(UTC) - timedelta(days=30)
    if dry_run:
        query = """
        MATCH (a)-[r]->(b)
        WHERE r.created_at < datetime($cutoff_date)
        RETURN count(r) as count
        """
        result = await neo4j_client.execute_query(query, cutoff_date=cutoff_date.isoformat())
        count = result.records[0]["count"] if result.records else 0
        return {
            "operation": "invalidate_edges",
            "result": {
                "dry_run": True,
                "stale_edges_found": count,
                "message": f"Found {count} stale edges",
            },
        }

    delete_query = """
    MATCH (a)-[r]->(b)
    WHERE r.created_at < datetime($cutoff_date)
    DELETE r
    RETURN count(r) as deleted
    """
    result = await neo4j_client.execute_query(delete_query, cutoff_date=cutoff_date.isoformat())
    deleted = result.records[0]["deleted"] if result.records else 0
    return {
        "operation": "invalidate_edges",
        "result": {
            "dry_run": False,
            "deleted": deleted,
            "message": f"Deleted {deleted} stale edges",
        },
    }


async def _run_rebuild_communities(
    dry_run: bool,
    group_id: str,
    project_id: str | None,
    workflow_engine: WorkflowEnginePort,
) -> dict[str, Any]:
    """Handle rebuild_communities operation for optimize_graph."""
    if dry_run:
        return {
            "operation": "rebuild_communities",
            "result": {"status": "skipped", "message": "Skipped in dry_run mode"},
        }

    from uuid import uuid4

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    task_payload = {"task_group_id": group_id, "project_id": project_id}
    task_id = str(uuid4())
    async with async_session_factory() as session, session.begin():
        task_log = TaskLog(
            id=task_id,
            group_id=group_id,
            task_type="rebuild_communities",
            status="PENDING",
            payload=task_payload,
            entity_type="community",
            created_at=datetime.now(UTC),
        )
        session.add(task_log)
    task_payload["task_id"] = task_id
    workflow_id = f"rebuild-communities-{group_id}-{task_id[:8]}"
    await workflow_engine.start_workflow(
        workflow_name="rebuild_communities",
        workflow_id=workflow_id,
        input_data=task_payload,
        task_queue="default",
    )
    return {
        "operation": "rebuild_communities",
        "result": {
            "status": "success",
            "message": "Community rebuild task submitted to Temporal",
            "task_id": task_id,
            "workflow_id": workflow_id,
        },
    }


@router.post("/optimize")
async def optimize_graph(
    operations: list[str] = Body(
        ["incremental_refresh", "deduplicate"],
        description="List of operations to run",
    ),
    dry_run: bool = Body(True, description="If true, report actions without executing"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> Any:
    """
    Run multiple optimization operations.

    Supported operations:
    - incremental_refresh: Refresh recent episodes
    - deduplicate: Remove duplicate entities
    - invalidate_edges: Remove stale edges
    - rebuild_communities: Rebuild community structure
    """
    assert neo4j_client is not None
    try:
        results = {
            "operations_run": [],
            "dry_run": dry_run,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        group_id = getattr(current_user, "project_id", None) or "neo4j"
        project_id = getattr(current_user, "project_id", None)
        tenant_id = getattr(current_user, "tenant_id", None)
        user_id = str(current_user.id)
        for operation in operations:
            if operation == "incremental_refresh":
                op_result = await _run_incremental_refresh(
                    group_id, tenant_id, project_id, user_id, workflow_engine
                )
                results["operations_run"].append(op_result)
            elif operation == "deduplicate":
                op_result = await _run_deduplicate(
                    dry_run, group_id, project_id, neo4j_client, workflow_engine
                )
                results["operations_run"].append(op_result)
            elif operation == "invalidate_edges":
                op_result = await _run_invalidate_edges(dry_run, neo4j_client)
                results["operations_run"].append(op_result)
            elif operation == "rebuild_communities":
                op_result = await _run_rebuild_communities(
                    dry_run, group_id, project_id, workflow_engine
                )
                results["operations_run"].append(op_result)
            else:
                logger.warning(f"Unknown operation: {operation}")
        return results
    except Exception as e:
        logger.error(f"Graph optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Embedding Management Endpoints ---


@router.get("/embeddings/status")
async def get_embedding_status(
    project_id: str | None = Query(None, description="Project ID to check"),
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Check embedding dimension status for a project.

    Returns information about current embedding dimensions, compatibility,
    and count of nodes missing embeddings.
    """
    try:
        from src.infrastructure.adapters.secondary.graphiti.embedding_utils import (
            get_existing_embedding_dimension,
        )
        from src.infrastructure.llm.provider_factory import get_ai_service_factory

        current_dim = graphiti_client.embedder.embedding_dim
        existing_dim = await get_existing_embedding_dimension(graphiti_client.driver)

        # Get provider name for display from DB config
        tenant_id = getattr(current_user, "tenant_id", "default")
        factory = get_ai_service_factory()
        try:
            provider_config = await factory.resolve_provider(tenant_id)
            provider = provider_config.provider
        except Exception:
            provider = "unknown"

        provider_name = {
            "gemini": "Gemini",
            "dashscope": "Dashscope",
            "openai": "OpenAI",
            "zai": "Z.AI",
            "deepseek": "Deepseek",
        }.get(provider, provider)

        # Count nodes without embeddings (for specific project if provided)
        if project_id:
            count_query = """
                MATCH (n:Entity {project_id: $project_id})
                WHERE n.name_embedding IS NULL
                RETURN count(n) AS missing_count
            """
            result = await graphiti_client.driver.execute_query(count_query, project_id=project_id)
            missing_count = result.records[0]["missing_count"] if result.records else 0
        else:
            missing_count = 0

        return {
            "current_provider": provider_name,
            "current_dimension": current_dim,
            "existing_dimension": existing_dim,
            "is_compatible": existing_dim is None or existing_dim == current_dim,
            "missing_embeddings": missing_count,
        }

    except Exception as e:
        logger.error(f"Failed to get embedding status: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/embeddings/rebuild")
async def rebuild_embeddings(
    project_id: str = Query(..., description="Project ID to rebuild embeddings for"),
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> dict[str, Any]:
    """
    Rebuild embeddings for a project after switching LLM providers.

    This operation regenerates all embedding vectors for entities in the project
    using the current embedder. Useful after switching LLM providers.
    """
    try:
        from src.infrastructure.adapters.secondary.graphiti.embedding_utils import (
            rebuild_embeddings_for_project,
        )

        embedder = graphiti_client.embedder

        result = await rebuild_embeddings_for_project(
            driver=graphiti_client.driver,
            embedder=embedder,
            project_id=project_id,
        )

        return {"status": "success", "result": result}

    except Exception as e:
        logger.error(f"Failed to rebuild embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/embeddings/dimensions/check")
async def check_embedding_dimensions(
    project_id: str | None = Query(None, description="Project ID to check"),
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> None:
    """
    Check for mixed embedding dimensions in Neo4j.

    Detects if there are embeddings with different dimensions in the database.
    Returns warning if mixed dimensions are detected, as this will cause
    vector similarity operations to fail.
    """
    try:
        from src.infrastructure.adapters.secondary.graphiti.embedding_utils import (
            detect_mixed_dimensions,
        )

        result = await detect_mixed_dimensions(
            driver=graphiti_client.driver,
            project_id=project_id,
        )

        # Add current embedder info
        result["current_dimension"] = graphiti_client.embedder.embedding_dim

        # Determine if action is needed
        if result["has_mixed_dimensions"]:
            result["action_required"] = "clear_mixed"
            result["message"] = (
                f"Mixed dimensions detected: {result['counts']}. "
                "Clear embeddings and rebuild with consistent provider."
            )
        elif result["total_embeddings"] == 0:
            result["action_required"] = "none"
            result["message"] = "No embeddings found in database."
        else:
            result["action_required"] = "none"
            result["message"] = (
                f"All embeddings have consistent dimension: {result['dimensions'][0]}"
            )

        return cast(None, result)

    except Exception as e:
        logger.error(f"Failed to check embedding dimensions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/embeddings/validate")
async def validate_embeddings(
    project_id: str | None = Query(None, description="Project ID to validate"),
    current_user: User = Depends(get_current_user),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> None:
    """
    Validate all embeddings in the database.

    Checks for:
    - Dimension mismatches
    - Zero vectors
    - NaN/Inf values

    Returns detailed validation report.
    """
    try:
        from src.infrastructure.adapters.secondary.graphiti.embedding_utils import (
            validate_embeddings_in_db,
        )

        expected_dim = graphiti_client.embedder.embedding_dim

        result = await validate_embeddings_in_db(
            driver=graphiti_client.driver,
            expected_dim=expected_dim,
            project_id=project_id,
        )

        return cast(None, result)

    except Exception as e:
        logger.error(f"Failed to validate embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Native Graph Adapter Embedding Management ---


@router.get("/embeddings/native/status")
async def get_native_embedding_status(
    project_id: str | None = Query(None, description="Project ID to check"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
) -> dict[str, Any]:
    """
    Get embedding dimension status using native graph adapter.

    Returns:
        - Current configured embedding dimension
        - Existing embedding dimension in Neo4j
        - Compatibility status
        - Vector index information
    """
    try:
        from src.configuration.config import get_settings
        from src.infrastructure.llm.provider_factory import get_ai_service_factory

        settings = get_settings()

        # Get current embedder dimension
        tenant_id = getattr(current_user, "tenant_id", "default")
        factory = get_ai_service_factory()

        try:
            provider_config = await factory.resolve_provider(tenant_id)
            provider = provider_config.provider
        except Exception:
            provider = "unknown"

        # Get configured dimension
        config_dim = settings.embedding_dimension

        # Get existing dimension from Neo4j
        existing_dim = await neo4j_client.get_vector_index_dimension("entity_name_vector")

        # Check for embeddings in database
        query_count = """
            MATCH (n:Entity)
            WHERE n.name_embedding IS NOT NULL
            RETURN count(n) AS total, n.embedding_dim AS dim
            ORDER BY total DESC
            LIMIT 5
        """
        result = await neo4j_client.execute_query(query_count)

        dimension_counts = {}
        total_embeddings = 0
        for record in result.records:
            dim = record.get("dim")
            count = record.get("total", 0)
            if dim:
                dimension_counts[str(dim)] = count
            total_embeddings += count

        # Determine compatibility
        if config_dim:
            target_dim = config_dim
        elif existing_dim:
            target_dim = existing_dim
        else:
            # Will be auto-detected from embedder
            target_dim = None

        is_compatible = existing_dim is None or target_dim is None or existing_dim == target_dim

        return {
            "configured_dimension": config_dim,
            "index_dimension": existing_dim,
            "target_dimension": target_dim,
            "is_compatible": is_compatible,
            "provider": provider,
            "total_embeddings": total_embeddings,
            "dimension_distribution": dimension_counts,
            "recommendations": _get_embedding_recommendations(
                config_dim, existing_dim, total_embeddings, is_compatible
            ),
        }

    except Exception as e:
        logger.error(f"Failed to get native embedding status: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


def _get_embedding_recommendations(
    config_dim: int | None,
    existing_dim: int | None,
    total_embeddings: int,
    is_compatible: bool,
) -> list[dict[str, Any]]:
    """Generate recommendations based on embedding status."""
    recommendations = []

    if not is_compatible:
        recommendations.append(
            {
                "type": "dimension_mismatch",
                "priority": "critical",
                "message": (
                    f"Dimension mismatch detected: configured={config_dim}, "
                    f"existing={existing_dim}. Vector search will fail."
                ),
                "action": "migrate_embeddings",
            }
        )

    if total_embeddings > 0 and existing_dim is None:
        recommendations.append(
            {
                "type": "index_missing",
                "priority": "high",
                "message": "Embeddings exist but no vector index found.",
                "action": "create_index",
            }
        )

    if total_embeddings == 0:
        recommendations.append(
            {
                "type": "no_embeddings",
                "priority": "low",
                "message": "No embeddings in database. They will be created on demand.",
                "action": "none",
            }
        )

    if is_compatible and total_embeddings > 0:
        recommendations.append(
            {
                "type": "healthy",
                "priority": "info",
                "message": f"Embedding system healthy. {total_embeddings} embeddings at {existing_dim}D.",
                "action": "none",
            }
        )

    return recommendations


def _resolve_target_dimension(target_model: str) -> int:
    """Resolve embedding dimension from model name."""
    from src.configuration.factories import EMBEDDING_DIMS

    model_lower = target_model.lower()
    for provider, dim in EMBEDDING_DIMS.items():
        if provider in model_lower:
            return dim

    fallback_dims = {"3072": 3072, "1536": 1536, "ada": 1536, "1024": 1024, "768": 768}
    for key, dim in fallback_dims.items():
        if key in model_lower:
            return dim

    raise HTTPException(
        status_code=400,
        detail=f"Unknown model dimension for: {target_model}",
    )


async def _query_entity_embeddings(
    neo4j_client: Neo4jClient,
    project_id: str | None,
) -> Any:
    """Query entity embeddings, optionally scoped to a project."""
    if project_id:
        query = """
            MATCH (n:Entity {project_id: $project_id})
            WHERE n.name_embedding IS NOT NULL
            RETURN count(n) AS count,
                   n.embedding_dim AS dim,
                   size(n.name_embedding) AS actual_dim
        """
        return await neo4j_client.execute_query(query, project_id=project_id)
    query = """
        MATCH (n:Entity)
        WHERE n.name_embedding IS NOT NULL
        RETURN count(n) AS count,
               n.embedding_dim AS dim,
               size(n.name_embedding) AS actual_dim
    """
    return await neo4j_client.execute_query(query)


async def _clear_entity_embeddings(
    neo4j_client: Neo4jClient,
    project_id: str | None,
) -> int:
    """Clear entity embeddings, optionally scoped to a project."""
    if project_id:
        query = """
            MATCH (n:Entity {project_id: $project_id})
            WHERE n.name_embedding IS NOT NULL
            REMOVE n.name_embedding, n.embedding_dim
            RETURN count(n) AS cleared
        """
        result = await neo4j_client.execute_query(query, project_id=project_id)
    else:
        query = """
            MATCH (n:Entity)
            WHERE n.name_embedding IS NOT NULL
            REMOVE n.name_embedding, n.embedding_dim
            RETURN count(n) AS cleared
        """
        result = await neo4j_client.execute_query(query)
    return result.records[0]["cleared"] if result.records else 0


@router.post("/embeddings/native/migrate")
async def migrate_embeddings(
    target_model: str = Query(
        ..., description="Target embedding model (e.g., 'text-embedding-3-small')"
    ),
    project_id: str | None = Query(None, description="Project ID to migrate"),
    dry_run: bool = Query(True, description="If true, only report without migrating"),
    current_user: User = Depends(get_current_user),
    neo4j_client: Neo4jClient | None = Depends(get_neo4j_client),
) -> dict[str, Any]:
    """
    Migrate embeddings to a new model dimension.

    This endpoint triggers embedding migration when switching models.
    In dry_run mode, reports what would be migrated.
    In execute mode, clears old embeddings (new ones generated on demand).

    Args:
        target_model: The target embedding model name
        project_id: Optional project ID to limit scope
        dry_run: If True, only report without executing
    """
    assert neo4j_client is not None
    try:
        target_dim = _resolve_target_dimension(target_model)
        # Get existing embeddings info
        result = await _query_entity_embeddings(neo4j_client, project_id)
        total_count = 0
        dimension_groups = {}
        for record in result.records:
            count = record.get("count", 0)
            dim = record.get("dim") or record.get("actual_dim")
            total_count += count
            if dim:
                dimension_groups[str(dim)] = dimension_groups.get(str(dim), 0) + count
            return {
                "dry_run": True,
                "target_model": target_model,
                "target_dimension": target_dim,
                "total_embeddings": total_count,
                "current_dimensions": dimension_groups,
                "action_required": total_count > 0,
                "message": (
                    f"Would migrate {total_count} embeddings from "
                    f"{list(dimension_groups.keys())} to {target_dim}D"
                ),
            }
        # Execute migration: clear old embeddings
        cleared = await _clear_entity_embeddings(neo4j_client, project_id)
        # Create new vector index with target dimension
        new_index_name = f"entity_name_vector_{target_dim}D"
        await neo4j_client.create_vector_index(
            index_name=new_index_name,
            label="Entity",
            property_name="name_embedding",
            dimensions=target_dim,
            similarity_function="cosine",
        )
        logger.info(
            f"Embedding migration completed: cleared {cleared} embeddings, "
            f"created index {new_index_name}"
        )

        return {
            "dry_run": False,
            "target_model": target_model,
            "target_dimension": target_dim,
            "embeddings_cleared": cleared,
            "new_index": new_index_name,
            "message": (
                f"Cleared {cleared} embeddings. New embeddings will be generated "
                f"on demand at {target_dim}D when entities are accessed."
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to migrate embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
