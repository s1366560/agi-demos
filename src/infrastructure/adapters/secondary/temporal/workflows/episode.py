"""Episode Processing Workflows for Temporal.

This module defines Workflows for processing episodes through the knowledge graph,
including entity extraction, relationship discovery, and community updates.
"""

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activities using workflow-safe imports
with workflow.unsafe.imports_passed_through():
    from src.infrastructure.adapters.secondary.temporal.activities.community import (
        update_communities_for_entities_activity,
    )
    from src.infrastructure.adapters.secondary.temporal.activities.episode import (
        add_episode_activity,
        extract_entities_activity,
        extract_relationships_activity,
        incremental_refresh_activity,
    )


@workflow.defn(name="episode_processing")
class EpisodeProcessingWorkflow:
    """Workflow for processing a single episode.

    This workflow orchestrates the complete episode processing pipeline:
    1. Episode ingestion and entity extraction
    2. Entity deduplication
    3. Relationship extraction
    4. Community updates

    The workflow wraps the existing EpisodeTaskHandler logic, providing:
    - Automatic retries with exponential backoff
    - Progress tracking via heartbeats
    - DAG-based orchestration for future fine-grained control
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the episode processing workflow.

        Args:
            input_data: Episode processing input containing:
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
            Processing result with statistics
        """
        # Default retry policy for activities
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(minutes=10),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        # Execute the main episode processing activity
        # This wraps the complete EpisodeTaskHandler logic
        result = await workflow.execute_activity(
            add_episode_activity,
            input_data,
            start_to_close_timeout=timedelta(seconds=600),
            heartbeat_timeout=timedelta(seconds=60),
            retry_policy=retry_policy,
        )

        return result


@workflow.defn(name="episode_processing_dag")
class EpisodeProcessingDAGWorkflow:
    """DAG-based workflow for fine-grained episode processing.

    This workflow provides more granular control over the processing pipeline,
    allowing parallel execution and conditional branching.

    Use this workflow when:
    - You need fine-grained progress tracking
    - You want to parallelize entity extraction
    - You need conditional community updates
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the DAG-based episode processing workflow.

        Args:
            input_data: Episode processing input

        Returns:
            Processing result with detailed statistics
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(minutes=5),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        episode_uuid = input_data.get("uuid")
        content = input_data.get("content", "")
        project_id = input_data.get("project_id")
        tenant_id = input_data.get("tenant_id")

        # Step 1: Extract entities
        workflow.logger.info(f"Step 1: Extracting entities for episode {episode_uuid}")
        entity_result = await workflow.execute_activity(
            extract_entities_activity,
            args=[episode_uuid, content, project_id, tenant_id],
            start_to_close_timeout=timedelta(seconds=300),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        entity_ids = entity_result.get("entity_ids", [])
        workflow.logger.info(f"Extracted {len(entity_ids)} entities")

        # Step 2: Extract relationships (only if entities found)
        relationship_count = 0
        if entity_ids:
            workflow.logger.info(f"Step 2: Extracting relationships for {len(entity_ids)} entities")
            rel_result = await workflow.execute_activity(
                extract_relationships_activity,
                args=[episode_uuid, entity_ids, project_id, tenant_id],
                start_to_close_timeout=timedelta(seconds=300),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=retry_policy,
            )
            relationship_count = rel_result.get("relationship_count", 0)

        # Step 3: Update communities (conditional - only if more than 5 entities)
        community_updated = False
        if len(entity_ids) > 5:
            workflow.logger.info(f"Step 3: Updating communities for {len(entity_ids)} entities")
            await workflow.execute_activity(
                update_communities_for_entities_activity,
                args=[entity_ids, project_id, tenant_id],
                start_to_close_timeout=timedelta(seconds=600),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=retry_policy,
            )
            community_updated = True
        else:
            workflow.logger.info("Step 3: Skipping community update (< 5 entities)")

        return {
            "status": "completed",
            "episode_uuid": episode_uuid,
            "entity_count": len(entity_ids),
            "relationship_count": relationship_count,
            "community_updated": community_updated,
        }


@workflow.defn(name="incremental_refresh")
class IncrementalRefreshWorkflow:
    """Workflow for incrementally refreshing episode processing.

    This workflow re-processes episodes to update the knowledge graph
    with improved extraction logic or to recover from processing issues.
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the incremental refresh workflow.

        Args:
            input_data: Refresh input containing:
                - project_id: Project to refresh
                - tenant_id: Tenant identifier
                - episode_ids: Optional list of specific episodes
                - force: Whether to force re-processing
                - task_id: Task log ID

        Returns:
            Refresh result with statistics
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(minutes=15),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        result = await workflow.execute_activity(
            incremental_refresh_activity,
            input_data,
            start_to_close_timeout=timedelta(seconds=3600),
            heartbeat_timeout=timedelta(seconds=120),
            retry_policy=retry_policy,
        )

        return result
