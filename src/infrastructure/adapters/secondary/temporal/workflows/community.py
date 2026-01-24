"""Community Workflows for Temporal.

This module defines Workflows for managing community structures
in the knowledge graph.
"""

from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activities using workflow-safe imports
with workflow.unsafe.imports_passed_through():
    from src.infrastructure.adapters.secondary.temporal.activities.community import (
        rebuild_communities_activity,
        update_communities_for_entities_activity,
    )


@workflow.defn(name="rebuild_communities")
class RebuildCommunitiesWorkflow:
    """Workflow for rebuilding community structures.

    This workflow orchestrates the complete community rebuild process:
    1. Community detection using Louvain algorithm
    2. Community summary generation
    3. Member assignment updates

    The workflow wraps RebuildCommunityTaskHandler logic with
    enterprise-grade orchestration capabilities.
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the community rebuild workflow.

        Args:
            input_data: Rebuild input containing:
                - project_id: Project identifier
                - tenant_id: Tenant identifier
                - task_id: Task log ID for progress tracking
                - force: Whether to force full rebuild

        Returns:
            Rebuild result with statistics
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(minutes=15),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        # Execute the main rebuild activity
        result = await workflow.execute_activity(
            rebuild_communities_activity,
            input_data,
            start_to_close_timeout=timedelta(seconds=3600),
            heartbeat_timeout=timedelta(seconds=120),
            retry_policy=retry_policy,
        )

        return result


@workflow.defn(name="batch_rebuild_communities")
class BatchRebuildCommunitiesWorkflow:
    """Workflow for rebuilding communities across multiple projects.

    This workflow handles batch community rebuilding with:
    - Parallel execution within batches
    - Progress tracking per project
    - Partial failure tolerance
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute batch community rebuild.

        Args:
            input_data: Batch input containing:
                - project_ids: List of project IDs to rebuild
                - tenant_id: Tenant identifier
                - batch_size: Number of parallel rebuilds (default: 10)

        Returns:
            Batch result with per-project status
        """
        project_ids: List[str] = input_data.get("project_ids", [])
        tenant_id = input_data.get("tenant_id")
        batch_size = input_data.get("batch_size", 10)

        if not project_ids:
            return {"status": "completed", "processed": 0, "results": []}

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(minutes=10),
            maximum_attempts=2,
            backoff_coefficient=2.0,
        )

        results = []
        failed_count = 0

        # Process in batches
        for i in range(0, len(project_ids), batch_size):
            batch = project_ids[i : i + batch_size]
            workflow.logger.info(f"Processing batch {i // batch_size + 1}: {len(batch)} projects")

            # Execute batch in parallel
            batch_tasks = []
            for project_id in batch:
                task = workflow.execute_activity(
                    rebuild_communities_activity,
                    {
                        "project_id": project_id,
                        "tenant_id": tenant_id,
                    },
                    start_to_close_timeout=timedelta(seconds=3600),
                    heartbeat_timeout=timedelta(seconds=120),
                    retry_policy=retry_policy,
                )
                batch_tasks.append((project_id, task))

            # Collect results
            for project_id, task in batch_tasks:
                try:
                    result = await task
                    results.append(
                        {
                            "project_id": project_id,
                            "status": "completed",
                            "result": result,
                        }
                    )
                except Exception as e:
                    failed_count += 1
                    results.append(
                        {
                            "project_id": project_id,
                            "status": "failed",
                            "error": str(e),
                        }
                    )

        return {
            "status": "completed" if failed_count == 0 else "partial",
            "processed": len(project_ids),
            "succeeded": len(project_ids) - failed_count,
            "failed": failed_count,
            "results": results,
        }


@workflow.defn(name="incremental_community_update")
class IncrementalCommunityUpdateWorkflow:
    """Workflow for incremental community updates.

    This workflow updates communities when new entities are added,
    without requiring a full rebuild.
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute incremental community update.

        Args:
            input_data: Update input containing:
                - entity_ids: List of new entity IDs
                - project_id: Project identifier
                - tenant_id: Tenant identifier

        Returns:
            Update result
        """
        entity_ids: List[str] = input_data.get("entity_ids", [])
        project_id = input_data.get("project_id")
        tenant_id = input_data.get("tenant_id")

        if not entity_ids:
            return {"status": "completed", "updated": 0}

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(minutes=5),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        # Step 1: Update communities for new entities
        workflow.logger.info(f"Updating communities for {len(entity_ids)} entities")
        await workflow.execute_activity(
            update_communities_for_entities_activity,
            args=[entity_ids, project_id, tenant_id],
            start_to_close_timeout=timedelta(seconds=600),
            heartbeat_timeout=timedelta(seconds=60),
            retry_policy=retry_policy,
        )

        return {
            "status": "completed",
            "entity_count": len(entity_ids),
            "project_id": project_id,
        }
