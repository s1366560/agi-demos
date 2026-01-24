"""Entity-related Activities for Temporal.

This module provides Activities for entity management operations through Temporal,
with inlined logic from DeduplicateEntitiesTaskHandler.
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


@activity.defn(name="deduplicate_entities")
async def deduplicate_entities_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deduplicate entities in the knowledge graph.

    This Activity performs:
    - Entity similarity detection using embeddings and name matching
    - Entity merging with relationship preservation
    - Metadata consolidation

    Args:
        payload: Deduplication payload containing:
            - project_id: Project identifier
            - tenant_id: Tenant identifier
            - task_id: Task log ID for progress tracking
            - similarity_threshold: Similarity threshold (0.0-1.0), default 0.9
            - dry_run: Whether to just report duplicates without merging, default True

    Returns:
        Result dictionary with deduplication statistics
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    # Extract payload parameters
    similarity_threshold = payload.get("similarity_threshold", 0.9)
    dry_run = payload.get("dry_run", True)
    project_id = payload.get("project_id")
    task_id = payload.get("task_id")

    info = activity.info()
    logger.info(
        f"Executing deduplicate_entities activity (workflow_id={info.workflow_id}, attempt={info.attempt})"
    )

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    neo4j_client = graph_service.client

    try:
        await update_task_progress(task_id, 10, "Fetching entities...")

        # Step 1: Get all entities in project
        query = """
        MATCH (e:Entity)
        WHERE e.project_id = $project_id OR $project_id IS NULL
        RETURN e.uuid as uuid, e.name as name, e.entity_type as entity_type,
               e.name_embedding as embedding
        """
        result = await neo4j_client.execute_query(query, project_id=project_id)

        entities = []
        for record in result.records:
            entities.append(
                {
                    "uuid": record["uuid"],
                    "name": record["name"],
                    "entity_type": record.get("entity_type", "unknown"),
                    "embedding": record.get("embedding"),
                }
            )

        logger.info(f"Found {len(entities)} entities for deduplication")

        if len(entities) < 2:
            logger.info("Not enough entities to deduplicate")
            await mark_task_completed(
                task_id,
                message="Not enough entities to deduplicate",
                result={"duplicate_pairs": 0, "merged_count": 0},
            )
            return {
                "status": "completed",
                "duplicate_pairs": 0,
                "merged_count": 0,
                "workflow_id": info.workflow_id,
            }

        await update_task_progress(task_id, 30, "Finding duplicates by name similarity...")

        # Step 2: Find duplicates using name similarity
        duplicate_pairs = await _find_duplicates_by_name(entities, similarity_threshold)

        # Step 3: Find duplicates using embedding similarity if embeddings available
        entities_with_embeddings = [e for e in entities if e.get("embedding")]
        if len(entities_with_embeddings) >= 2:
            await update_task_progress(task_id, 50, "Finding duplicates by embedding similarity...")
            embedding_duplicates = await _find_duplicates_by_embedding(
                entities_with_embeddings, similarity_threshold
            )
            # Merge duplicate sets
            for pair in embedding_duplicates:
                if pair not in duplicate_pairs:
                    duplicate_pairs.append(pair)

        logger.info(f"Found {len(duplicate_pairs)} duplicate pairs")

        await update_task_progress(task_id, 70, f"Found {len(duplicate_pairs)} duplicate pairs")

        if dry_run:
            logger.info("Dry run mode - not merging duplicates")
            await mark_task_completed(
                task_id,
                message=f"Dry run: found {len(duplicate_pairs)} duplicates",
                result={
                    "duplicate_pairs": len(duplicate_pairs),
                    "merged_count": 0,
                    "dry_run": True,
                },
            )
            return {
                "status": "completed",
                "duplicate_pairs": len(duplicate_pairs),
                "merged_count": 0,
                "dry_run": True,
                "workflow_id": info.workflow_id,
            }

        # Step 4: Merge duplicates
        await update_task_progress(task_id, 80, "Merging duplicates...")
        merged_count = 0
        for duplicate_uuid, original_uuid in duplicate_pairs:
            try:
                await _merge_entities(neo4j_client, duplicate_uuid, original_uuid, project_id)
                merged_count += 1
            except Exception as e:
                logger.error(f"Failed to merge {duplicate_uuid} into {original_uuid}: {e}")

        logger.info(f"Merged {merged_count} duplicate entities")

        await mark_task_completed(
            task_id,
            message=f"Merged {merged_count} duplicate entities",
            result={"duplicate_pairs": len(duplicate_pairs), "merged_count": merged_count},
        )

        return {
            "status": "completed",
            "duplicate_pairs": len(duplicate_pairs),
            "merged_count": merged_count,
            "workflow_id": info.workflow_id,
        }

    except Exception as e:
        logger.error(f"Deduplication failed: {e}")
        await mark_task_failed(task_id, str(e))
        raise


async def _find_duplicates_by_name(entities: List[Dict], threshold: float) -> List[tuple]:
    """Find duplicate entities by name similarity."""
    duplicates = []
    processed = set()

    for i, entity1 in enumerate(entities):
        if entity1["uuid"] in processed:
            continue

        for j, entity2 in enumerate(entities[i + 1 :], i + 1):
            if entity2["uuid"] in processed:
                continue

            # Simple name similarity check
            name1 = entity1["name"].lower().strip()
            name2 = entity2["name"].lower().strip()

            # Exact match or very similar
            if name1 == name2:
                duplicates.append((entity2["uuid"], entity1["uuid"]))
                processed.add(entity2["uuid"])
            elif _name_similarity(name1, name2) >= threshold:
                duplicates.append((entity2["uuid"], entity1["uuid"]))
                processed.add(entity2["uuid"])

    return duplicates


def _name_similarity(name1: str, name2: str) -> float:
    """Calculate simple name similarity using Jaccard index."""
    if not name1 or not name2:
        return 0.0

    # Use character-level comparison for short strings
    set1 = set(name1.lower())
    set2 = set(name2.lower())

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    return intersection / union if union > 0 else 0.0


async def _find_duplicates_by_embedding(entities: List[Dict], threshold: float) -> List[tuple]:
    """Find duplicate entities by embedding similarity."""
    import numpy as np

    duplicates = []
    processed = set()

    embeddings = []
    valid_entities = []

    for entity in entities:
        if entity.get("embedding"):
            embeddings.append(entity["embedding"])
            valid_entities.append(entity)

    if len(embeddings) < 2:
        return duplicates

    # Convert to numpy arrays
    embeddings_array = np.array(embeddings)

    # Normalize embeddings
    norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
    normalized = embeddings_array / (norms + 1e-10)

    # Calculate cosine similarities
    similarities = np.dot(normalized, normalized.T)

    for i in range(len(valid_entities)):
        if valid_entities[i]["uuid"] in processed:
            continue

        for j in range(i + 1, len(valid_entities)):
            if valid_entities[j]["uuid"] in processed:
                continue

            if similarities[i, j] >= threshold:
                duplicates.append((valid_entities[j]["uuid"], valid_entities[i]["uuid"]))
                processed.add(valid_entities[j]["uuid"])

    return duplicates


async def _merge_entities(
    neo4j_client, duplicate_uuid: str, original_uuid: str, project_id: str | None
):
    """Merge duplicate entity into original entity."""
    # Redirect relationships (avoid creating duplicates)
    redirect_query = """
    MATCH (duplicate:Entity {uuid: $duplicate_uuid})-[r]-(other)
    WHERE NOT other.uuid = $original_uuid
    WITH duplicate, r, other, type(r) as rel_type
    MATCH (original:Entity {uuid: $original_uuid})
    WHERE NOT exists((original)-[]->(other)) AND NOT exists((other)-[]->(original))
    CALL apoc.create.relationship(original, rel_type, properties(r), other) YIELD rel
    DELETE r
    """

    try:
        await neo4j_client.execute_query(
            redirect_query, duplicate_uuid=duplicate_uuid, original_uuid=original_uuid
        )
    except Exception:
        # Fallback without APOC
        fallback_query = """
        MATCH (duplicate:Entity {uuid: $duplicate_uuid})-[r:RELATES_TO]-(other)
        WHERE NOT other.uuid = $original_uuid
        WITH duplicate, r, other
        MATCH (original:Entity {uuid: $original_uuid})
        MERGE (original)-[:RELATES_TO]->(other)
        DELETE r
        """
        await neo4j_client.execute_query(
            fallback_query, duplicate_uuid=duplicate_uuid, original_uuid=original_uuid
        )

    # Handle community memberships
    community_query = """
    MATCH (duplicate:Entity {uuid: $duplicate_uuid})-[:BELONGS_TO]->(c:Community)
    MATCH (original:Entity {uuid: $original_uuid})
    MERGE (original)-[:BELONGS_TO]->(c)
    """
    await neo4j_client.execute_query(
        community_query, duplicate_uuid=duplicate_uuid, original_uuid=original_uuid
    )

    # Delete duplicate
    delete_query = """
    MATCH (duplicate:Entity {uuid: $duplicate_uuid})
    DETACH DELETE duplicate
    """
    await neo4j_client.execute_query(delete_query, duplicate_uuid=duplicate_uuid)


@activity.defn(name="merge_entities")
async def merge_entities_activity(
    source_entity_id: str,
    target_entity_id: str,
    project_id: str,
    tenant_id: str = None,
) -> Dict[str, Any]:
    """Merge two duplicate entities (fine-grained Activity).

    This is a fine-grained Activity for merging specific entity pairs
    identified as duplicates.

    Args:
        source_entity_id: Entity to merge from (will be deleted)
        target_entity_id: Entity to merge into (will be kept)
        project_id: Project identifier
        tenant_id: Optional tenant identifier

    Returns:
        Dictionary with merge result
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    logger.info(f"Merging entity {source_entity_id} into {target_entity_id}")

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    try:
        neo4j_client = graph_service.client

        # Transfer relationships from source to target
        transfer_query = """
        MATCH (source:Entity {uuid: $source_id})
        MATCH (target:Entity {uuid: $target_id})
        
        // Transfer outgoing RELATES_TO relationships
        OPTIONAL MATCH (source)-[r:RELATES_TO]->(other:Entity)
        WHERE other.uuid <> $target_id
        WITH source, target, r, other
        CALL apoc.do.when(
            r IS NOT NULL,
            'MERGE (target)-[:RELATES_TO {weight: coalesce(r.weight, 1.0)}]->(other) RETURN 1',
            'RETURN 0',
            {target: target, other: other, r: r}
        ) YIELD value
        
        // Transfer incoming RELATES_TO relationships
        OPTIONAL MATCH (other2:Entity)-[r2:RELATES_TO]->(source)
        WHERE other2.uuid <> $target_id
        WITH source, target, r2, other2
        CALL apoc.do.when(
            r2 IS NOT NULL,
            'MERGE (other2)-[:RELATES_TO {weight: coalesce(r2.weight, 1.0)}]->(target) RETURN 1',
            'RETURN 0',
            {target: target, other2: other2, r2: r2}
        ) YIELD value AS val2
        
        // Transfer MENTIONS relationships
        OPTIONAL MATCH (ep:Episodic)-[m:MENTIONS]->(source)
        WITH source, target, ep, m
        CALL apoc.do.when(
            m IS NOT NULL,
            'MERGE (ep)-[:MENTIONS]->(target) RETURN 1',
            'RETURN 0',
            {target: target, ep: ep, m: m}
        ) YIELD value AS val3
        
        // Delete source entity and its relationships
        DETACH DELETE source
        
        RETURN count(*) as operations
        """

        await neo4j_client.execute_query(
            transfer_query,
            source_id=source_entity_id,
            target_id=target_entity_id,
        )

        activity.heartbeat({"status": "merged"})

        return {
            "status": "completed",
            "source_entity_id": source_entity_id,
            "target_entity_id": target_entity_id,
            "merged": True,
        }

    except Exception as e:
        logger.error(f"Entity merge failed: {e}")
        raise


@activity.defn(name="find_duplicate_entities")
async def find_duplicate_entities_activity(
    project_id: str,
    tenant_id: str = None,
    threshold: float = 0.85,
    limit: int = 100,
) -> Dict[str, Any]:
    """Find duplicate entity pairs (fine-grained Activity).

    Args:
        project_id: Project identifier
        tenant_id: Optional tenant identifier
        threshold: Similarity threshold (0.0-1.0)
        limit: Maximum number of pairs to return

    Returns:
        Dictionary with duplicate pairs
    """
    from src.infrastructure.adapters.secondary.temporal.worker_state import get_graph_service

    logger.info(f"Finding duplicate entities for project {project_id}, threshold={threshold}")

    graph_service = get_graph_service()
    if not graph_service:
        raise RuntimeError("Graph service not initialized")

    try:
        neo4j_client = graph_service.client

        # Find entities with similar embeddings
        query = """
        MATCH (e1:Entity)
        WHERE e1.project_id = $project_id
          AND e1.embedding IS NOT NULL
        MATCH (e2:Entity)
        WHERE e2.project_id = $project_id
          AND e2.embedding IS NOT NULL
          AND id(e1) < id(e2)
        WITH e1, e2, gds.similarity.cosine(e1.embedding, e2.embedding) AS similarity
        WHERE similarity >= $threshold
        RETURN e1.uuid AS source_id, e2.uuid AS target_id, similarity
        ORDER BY similarity DESC
        LIMIT $limit
        """

        records, _, _ = await neo4j_client.execute_query(
            query,
            project_id=project_id,
            threshold=threshold,
            limit=limit,
        )

        pairs = [
            {
                "source_id": record["source_id"],
                "target_id": record["target_id"],
                "similarity": record["similarity"],
            }
            for record in records
        ]

        activity.heartbeat({"pair_count": len(pairs)})

        return {
            "status": "completed",
            "duplicate_pairs": pairs,
            "pair_count": len(pairs),
            "threshold": threshold,
        }

    except Exception as e:
        logger.error(f"Duplicate detection failed for project {project_id}: {e}")
        raise
