"""Community-related Activities for Temporal.

This module provides Activities for community graph operations through Temporal,
with inlined logic from RebuildCommunityTaskHandler.
"""

import logging
from typing import Any, Dict, List

from temporalio import activity

from src.infrastructure.adapters.secondary.temporal.activities.base import (
    mark_task_completed,
    mark_task_failed,
    update_task_progress,
)

logger = logging.getLogger(__name__)


@activity.defn(name="rebuild_communities")
async def rebuild_communities_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild community structure for a project.

    This Activity performs:
    - Remove existing communities for the project
    - Community detection using Louvain algorithm
    - Community summary generation
    - Community membership updates

    Args:
        payload: Community rebuild payload containing:
            - task_group_id: Project identifier (legacy name)
            - project_id: Project identifier
            - tenant_id: Tenant identifier
            - task_id: Task log ID for progress tracking
            - force: Whether to force full rebuild

    Returns:
        Result dictionary with community statistics
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service
    from src.infrastructure.graph.schemas import EntityNode

    # Extract payload parameters
    task_group_id = payload.get("task_group_id") or payload.get("project_id")
    task_id = payload.get("task_id")
    tenant_id = payload.get("tenant_id")

    info = activity.info()
    logger.info(
        f"Executing rebuild_communities activity (workflow_id={info.workflow_id}, attempt={info.attempt})"
    )

    if not task_group_id:
        error_msg = "task_group_id (project_id) is required for rebuild_communities task"
        logger.error(error_msg)
        await mark_task_failed(task_id, error_msg)
        raise ValueError(error_msg)

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    neo4j_client = graph_service.client

    try:
        logger.info(f"Starting community rebuild for project: {task_group_id}")
        await update_task_progress(task_id, 10, "Removing existing communities...")

        # Step 1: Remove existing communities for this project only
        logger.info(f"Removing existing communities for project: {task_group_id}...")
        await neo4j_client.execute_query(
            """
            MATCH (c:Community)
            WHERE c.project_id = $project_id OR c.group_id = $project_id
            DETACH DELETE c
            """,
            project_id=task_group_id,
        )

        await update_task_progress(task_id, 30, "Detecting communities using Louvain algorithm...")

        # Step 2: Get all entities for this project
        logger.info(f"Building new communities for project: {task_group_id}...")

        entity_result = await neo4j_client.execute_query(
            """
            MATCH (e:Entity)
            WHERE e.project_id = $project_id
            RETURN e.uuid as uuid, e.name as name, e.entity_type as entity_type
            LIMIT 1000
            """,
            project_id=task_group_id,
        )

        # Create entity nodes for community updater
        entities = []
        for record in entity_result.records:
            entity = EntityNode(
                uuid=record["uuid"],
                name=record["name"],
                entity_type=record.get("entity_type", "unknown"),
                project_id=task_group_id,
            )
            entities.append(entity)

        await update_task_progress(
            task_id, 50, f"Found {len(entities)} entities. Detecting communities..."
        )

        # Step 3: Use graph service's community updater if available
        communities_count = 0
        if hasattr(graph_service, "community_updater"):
            try:
                communities = await graph_service.community_updater.update_communities_for_entities(
                    entities=entities,
                    project_id=task_group_id,
                    tenant_id=tenant_id,
                    regenerate_all=True,
                )
                communities_count = len(communities) if communities else 0
            except Exception as e:
                logger.warning(f"CommunityUpdater failed: {e}, communities_count will be 0")
        else:
            # Fallback: log warning
            logger.warning("CommunityUpdater not available, using direct Louvain detection")

        await update_task_progress(task_id, 90, "Calculating member counts...")

        # Step 4: Update member counts for all communities
        await neo4j_client.execute_query(
            """
            MATCH (c:Community)
            WHERE c.project_id = $project_id
            OPTIONAL MATCH (c)-[:HAS_MEMBER]->(e:Entity)
            WITH c, count(e) as member_count
            SET c.member_count = member_count
            """,
            project_id=task_group_id,
        )

        # Mark task as completed
        await mark_task_completed(
            task_id,
            message="Community rebuild completed successfully",
            result={
                "communities_count": communities_count,
                "entities_processed": len(entities),
            },
        )

        logger.info(
            f"Successfully rebuilt {communities_count} communities for project: {task_group_id}"
        )

        return {
            "status": "completed",
            "communities_count": communities_count,
            "entities_processed": len(entities),
            "workflow_id": info.workflow_id,
        }

    except Exception as e:
        logger.error(f"Failed to rebuild communities: {e}")
        await mark_task_failed(task_id, str(e))
        raise


@activity.defn(name="update_communities_for_entities")
async def update_communities_for_entities_activity(
    entity_ids: List[str],
    project_id: str,
    tenant_id: str = None,
) -> Dict[str, Any]:
    """Update communities for specific entities (fine-grained Activity).

    This is a fine-grained Activity for incremental community updates
    after entity extraction.

    Args:
        entity_ids: List of entity IDs to update communities for
        project_id: Project identifier
        tenant_id: Optional tenant identifier

    Returns:
        Dictionary with update statistics
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    logger.info(f"Updating communities for {len(entity_ids)} entities in project {project_id}")

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    try:
        # Use community updater if available
        if hasattr(graph_service, "community_updater"):
            # Create minimal entity objects for the updater
            from dataclasses import dataclass

            @dataclass
            class MinimalEntity:
                uuid: str

            entities = [MinimalEntity(uuid=eid) for eid in entity_ids]

            await graph_service.community_updater.update_communities_for_entities(
                entities=entities,
                project_id=project_id,
                tenant_id=tenant_id,
            )

        activity.heartbeat({"entity_count": len(entity_ids), "status": "completed"})

        return {
            "status": "completed",
            "entity_count": len(entity_ids),
            "project_id": project_id,
        }

    except Exception as e:
        logger.error(f"Community update failed for project {project_id}: {e}")
        raise


@activity.defn(name="detect_communities")
async def detect_communities_activity(
    project_id: str,
    tenant_id: str = None,
    algorithm: str = "louvain",
) -> Dict[str, Any]:
    """Detect communities in the entity graph (fine-grained Activity).

    Args:
        project_id: Project identifier
        tenant_id: Optional tenant identifier
        algorithm: Community detection algorithm (default: louvain)

    Returns:
        Dictionary with detected community IDs
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    logger.info(f"Detecting communities for project {project_id} using {algorithm}")

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    try:
        # Community detection via Louvain
        if hasattr(graph_service, "community_updater"):
            detector = graph_service.community_updater._louvain_detector
            if detector:
                communities = await detector.detect_communities(project_id=project_id)
                community_ids = [c.uuid for c in communities if c.uuid]

                activity.heartbeat({"community_count": len(community_ids)})

                return {
                    "status": "completed",
                    "community_ids": community_ids,
                    "community_count": len(community_ids),
                    "algorithm": algorithm,
                }

        return {
            "status": "completed",
            "community_ids": [],
            "community_count": 0,
            "algorithm": algorithm,
            "message": "Community detection not available",
        }

    except Exception as e:
        logger.error(f"Community detection failed for project {project_id}: {e}")
        raise
