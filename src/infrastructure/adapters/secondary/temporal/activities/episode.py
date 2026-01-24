"""Episode-related Activities for Temporal.

This module provides Activities for episode processing through Temporal,
with inlined logic from EpisodeTaskHandler and IncrementalRefreshTaskHandler.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from temporalio import activity

from src.infrastructure.adapters.secondary.temporal.activities.base import (
    mark_task_completed,
    mark_task_failed,
    update_memory_status,
    update_task_progress,
)

logger = logging.getLogger(__name__)


@activity.defn(name="add_episode")
async def add_episode_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process an episode through the knowledge graph.

    This Activity performs:
    - Entity extraction from episode content
    - Entity deduplication
    - Relationship extraction
    - Community updates
    - Metadata propagation

    Args:
        payload: Episode processing payload containing:
            - uuid: Episode unique identifier
            - content: Episode content text
            - name: Episode name
            - group_id: Group identifier (usually project_id)
            - project_id: Project identifier
            - tenant_id: Tenant identifier
            - user_id: User identifier
            - memory_id: Associated memory ID
            - task_id: Task log ID for progress tracking

    Returns:
        Result dictionary with status and metadata
    """
    from src.domain.model.enums import ProcessingStatus
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    # Extract payload parameters
    uuid = payload.get("uuid")
    group_id = payload.get("group_id")
    memory_id = payload.get("memory_id")
    project_id = payload.get("project_id")
    tenant_id = payload.get("tenant_id")
    user_id = payload.get("user_id")
    task_id = payload.get("task_id")
    content = payload.get("content", "")
    name = payload.get("name", "")

    info = activity.info()
    logger.info(
        f"Executing add_episode activity (workflow_id={info.workflow_id}, attempt={info.attempt})"
    )

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    neo4j_client = graph_service.client

    try:
        # Update Memory status to PROCESSING
        if memory_id:
            await update_memory_status(memory_id, ProcessingStatus.PROCESSING)

        await update_task_progress(task_id, 10, "Starting episode ingestion...")

        # Create or update Episodic node
        await update_task_progress(task_id, 20, "Creating episode node...")

        query = """
            MERGE (e:Episodic {uuid: $uuid})
            SET e:Node,
                e.name = $name,
                e.content = $content,
                e.group_id = $group_id,
                e.tenant_id = $tenant_id,
                e.project_id = $project_id,
                e.user_id = $user_id,
                e.memory_id = $memory_id,
                e.status = 'Processing',
                e.created_at = datetime($created_at)
        """
        await neo4j_client.execute_query(
            query,
            uuid=uuid,
            name=name or uuid,
            content=content,
            group_id=group_id or project_id or "global",
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            memory_id=memory_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        await update_task_progress(task_id, 30, "Extracting entities and relationships...")

        # Process episode using NativeGraphAdapter
        result = await graph_service.process_episode(
            episode_uuid=uuid,
            content=content,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        await update_task_progress(task_id, 70, "Updating episode status...")

        # Update episode status to Synced
        query = """
            MATCH (ep:Episodic {uuid: $uuid})
            SET ep.status = 'Synced'
        """
        await neo4j_client.execute_query(query, uuid=uuid)

        await update_task_progress(task_id, 80, "Updating communities...")

        # Update communities for extracted entities
        entity_count = 0
        relationship_count = 0

        if result and result.nodes and hasattr(graph_service, "community_updater"):
            entity_count = len(result.nodes)
            relationship_count = len(result.edges) if result.edges else 0

            try:
                await graph_service.community_updater.update_communities_for_entities(
                    entities=result.nodes,
                    project_id=project_id,
                    tenant_id=tenant_id,
                )

                # Propagate metadata to communities
                if tenant_id or project_id:
                    query = """
                    MATCH (ep:Episodic {uuid: $uuid})-[:MENTIONS]->(e:Entity)-[:BELONGS_TO]->(c:Community)
                    SET c.tenant_id = $tenant_id,
                        c.project_id = $project_id,
                        c.member_count = coalesce(c.member_count, 0)
                    """
                    await neo4j_client.execute_query(
                        query, uuid=uuid, tenant_id=tenant_id, project_id=project_id
                    )
            except Exception as e:
                logger.warning(f"Failed to update communities for episode {uuid}: {e}")

        # Mark task as completed
        await mark_task_completed(
            task_id,
            message="Episode ingestion completed",
            result={
                "entity_count": entity_count,
                "relationship_count": relationship_count,
            },
        )

        # Update Memory status to COMPLETED
        if memory_id:
            await update_memory_status(memory_id, ProcessingStatus.COMPLETED)

        logger.info(
            f"Episode {uuid} processed successfully: "
            f"{entity_count} entities, {relationship_count} relationships"
        )

        return {
            "status": "completed",
            "episode_uuid": uuid,
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "workflow_id": info.workflow_id,
        }

    except Exception as e:
        logger.error(f"Failed to process episode {uuid}: {e}")

        # Update Memory status to FAILED
        if memory_id:
            await update_memory_status(memory_id, ProcessingStatus.FAILED)

        # Mark task as failed
        await mark_task_failed(task_id, str(e))

        # Update episode status to Failed
        try:
            query = """
                MATCH (ep:Episodic {uuid: $uuid})
                SET ep.status = 'Failed'
            """
            await neo4j_client.execute_query(query, uuid=uuid)
        except Exception:
            pass

        raise


@activity.defn(name="incremental_refresh")
async def incremental_refresh_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Incrementally refresh episode processing.

    This Activity re-processes episodes to update the knowledge graph
    with new extraction logic.

    Args:
        payload: Refresh payload containing:
            - project_id: Project to refresh
            - tenant_id: Tenant identifier
            - user_id: User identifier
            - episode_uuids: Optional list of specific episodes to refresh
            - rebuild_communities: Whether to rebuild communities after refresh
            - task_id: Task log ID for progress tracking

    Returns:
        Result dictionary with refresh statistics
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    # Extract payload parameters
    episode_uuids = payload.get("episode_uuids")
    project_id = payload.get("project_id")
    tenant_id = payload.get("tenant_id")
    user_id = payload.get("user_id")
    rebuild_communities = payload.get("rebuild_communities", False)
    task_id = payload.get("task_id")

    info = activity.info()
    logger.info(
        f"Executing incremental_refresh activity (workflow_id={info.workflow_id}, attempt={info.attempt})"
    )

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    neo4j_client = graph_service.client

    try:
        await update_task_progress(task_id, 10, "Fetching episodes to refresh...")

        # Get episodes to refresh
        if episode_uuids:
            episodes = await _get_episodes_by_uuids(neo4j_client, episode_uuids)
        else:
            # Get recent episodes (last 24 hours)
            episodes = await _get_recent_episodes(neo4j_client, project_id)

        logger.info(f"Incremental refresh: processing {len(episodes)} episodes")
        await update_task_progress(task_id, 20, f"Found {len(episodes)} episodes to refresh")

        if not episodes:
            logger.info("No episodes to refresh")
            await mark_task_completed(
                task_id,
                message="No episodes to refresh",
                result={"processed_count": 0},
            )
            return {
                "status": "completed",
                "processed_count": 0,
                "workflow_id": info.workflow_id,
            }

        # Reprocess each episode
        processed_count = 0
        total = len(episodes)

        for i, episode in enumerate(episodes):
            progress = 20 + int((i / total) * 60)
            await update_task_progress(task_id, progress, f"Processing episode {i + 1}/{total}...")

            await _reprocess_episode(
                graph_service,
                neo4j_client,
                episode,
                project_id,
                tenant_id,
                user_id,
            )
            processed_count += 1

        await update_task_progress(task_id, 85, f"Processed {processed_count} episodes")

        # Optionally trigger community rebuild (as a separate workflow)
        if rebuild_communities and project_id:
            await update_task_progress(
                task_id, 90, "Community rebuild should be triggered separately..."
            )
            logger.info("Community rebuild requested - should be triggered as separate workflow")

        logger.info(f"Incremental refresh completed: {processed_count} episodes processed")

        await mark_task_completed(
            task_id,
            message=f"Completed: {processed_count} episodes refreshed",
            result={"processed_count": processed_count},
        )

        return {
            "status": "completed",
            "processed_count": processed_count,
            "workflow_id": info.workflow_id,
        }

    except Exception as e:
        logger.error(f"Incremental refresh failed: {e}")
        await mark_task_failed(task_id, str(e))
        raise


async def _get_episodes_by_uuids(neo4j_client, uuids: List[str]) -> List[Dict]:
    """Fetch specific episodes by UUIDs."""
    if not uuids:
        return []

    query = """
    MATCH (e:Episodic)
    WHERE e.uuid IN $uuids
    RETURN e.uuid as uuid, e.name as name, e.content as content,
           e.source_description as source_description,
           e.valid_at as valid_at, e.project_id as project_id,
           e.tenant_id as tenant_id, e.user_id as user_id
    """
    result = await neo4j_client.execute_query(query, uuids=uuids)

    episodes = []
    for record in result.records:
        episodes.append(
            {
                "uuid": record["uuid"],
                "name": record["name"],
                "content": record["content"],
                "source_description": record.get("source_description"),
                "valid_at": record.get("valid_at"),
                "project_id": record.get("project_id"),
                "tenant_id": record.get("tenant_id"),
                "user_id": record.get("user_id"),
            }
        )

    return episodes


async def _get_recent_episodes(
    neo4j_client, project_id: str | None, hours: int = 24, limit: int = 100
) -> List[Dict]:
    """Get recent episodes from the last N hours."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    query = """
    MATCH (e:Episodic)
    WHERE ($project_id IS NULL OR e.project_id = $project_id)
      AND e.created_at >= datetime($cutoff_time)
    RETURN e.uuid as uuid, e.name as name, e.content as content,
           e.source_description as source_description,
           e.valid_at as valid_at, e.project_id as project_id,
           e.tenant_id as tenant_id, e.user_id as user_id
    ORDER BY e.created_at DESC
    LIMIT $limit
    """
    result = await neo4j_client.execute_query(
        query,
        project_id=project_id,
        cutoff_time=cutoff_time.isoformat(),
        limit=limit,
    )

    episodes = []
    for record in result.records:
        episodes.append(
            {
                "uuid": record["uuid"],
                "name": record["name"],
                "content": record["content"],
                "source_description": record.get("source_description"),
                "valid_at": record.get("valid_at"),
                "project_id": record.get("project_id"),
                "tenant_id": record.get("tenant_id"),
                "user_id": record.get("user_id"),
            }
        )

    return episodes


async def _reprocess_episode(
    graph_service,
    neo4j_client,
    episode: Dict,
    project_id: str | None,
    tenant_id: str | None,
    user_id: str | None,
):
    """Reprocess a single episode using NativeGraphAdapter."""
    episode_uuid = episode["uuid"]
    content = episode.get("content", "")

    # Use project_id from payload or episode
    effective_project_id = project_id or episode.get("project_id")
    effective_tenant_id = tenant_id or episode.get("tenant_id")
    effective_user_id = user_id or episode.get("user_id")

    try:
        # Clear existing relationships from this episode
        clear_query = """
        MATCH (ep:Episodic {uuid: $uuid})-[r:MENTIONS]->(e:Entity)
        DELETE r
        """
        await neo4j_client.execute_query(clear_query, uuid=episode_uuid)

        # Reprocess using NativeGraphAdapter
        await graph_service.process_episode(
            episode_uuid=episode_uuid,
            content=content,
            project_id=effective_project_id,
            tenant_id=effective_tenant_id,
            user_id=effective_user_id,
        )

        # Update episode status
        status_query = """
        MATCH (ep:Episodic {uuid: $uuid})
        SET ep.status = 'Synced',
            ep.refreshed_at = datetime($refreshed_at)
        """
        await neo4j_client.execute_query(
            status_query,
            uuid=episode_uuid,
            refreshed_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.debug(f"Reprocessed episode {episode_uuid}")

    except Exception as e:
        logger.error(f"Failed to reprocess episode {episode_uuid}: {e}")
        # Update status to failed but don't stop the batch
        try:
            fail_query = """
            MATCH (ep:Episodic {uuid: $uuid})
            SET ep.status = 'RefreshFailed'
            """
            await neo4j_client.execute_query(fail_query, uuid=episode_uuid)
        except Exception:
            pass


@activity.defn(name="extract_entities")
async def extract_entities_activity(
    episode_uuid: str,
    content: str,
    project_id: str,
    tenant_id: str = None,
) -> Dict[str, Any]:
    """Extract entities from episode content (fine-grained Activity).

    This is a fine-grained Activity for DAG workflows that need
    more control over the extraction pipeline.

    Args:
        episode_uuid: Episode unique identifier
        content: Episode content text
        project_id: Project identifier
        tenant_id: Optional tenant identifier

    Returns:
        Dictionary with extracted entity_ids
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    logger.info(f"Extracting entities for episode {episode_uuid}")

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    try:
        # Use graph service entity extractor
        result = await graph_service._entity_extractor.extract(
            content=content,
            project_id=project_id,
        )

        entity_ids = [e.uuid for e in result.entities] if result and result.entities else []

        activity.heartbeat({"entity_count": len(entity_ids)})

        return {
            "status": "completed",
            "episode_uuid": episode_uuid,
            "entity_ids": entity_ids,
            "entity_count": len(entity_ids),
        }

    except Exception as e:
        logger.error(f"Entity extraction failed for {episode_uuid}: {e}")
        raise


@activity.defn(name="extract_relationships")
async def extract_relationships_activity(
    episode_uuid: str,
    entity_ids: list[str],
    project_id: str,
    tenant_id: str = None,
) -> Dict[str, Any]:
    """Extract relationships between entities (fine-grained Activity).

    Args:
        episode_uuid: Episode unique identifier
        entity_ids: List of entity IDs to find relationships between
        project_id: Project identifier
        tenant_id: Optional tenant identifier

    Returns:
        Dictionary with relationship count
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    logger.info(f"Extracting relationships for episode {episode_uuid}")

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    try:
        # Relationship extraction is part of process_episode
        # This is a placeholder for fine-grained control
        activity.heartbeat({"status": "extracting_relationships"})

        return {
            "status": "completed",
            "episode_uuid": episode_uuid,
            "entity_count": len(entity_ids),
        }

    except Exception as e:
        logger.error(f"Relationship extraction failed for {episode_uuid}: {e}")
        raise
