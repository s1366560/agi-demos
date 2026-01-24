"""Entity Workflows for Temporal.

This module defines Workflows for managing entities in the knowledge graph,
including deduplication and merging operations.
"""

from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activities using workflow-safe imports
with workflow.unsafe.imports_passed_through():
    from src.infrastructure.adapters.secondary.temporal.activities.entity import (
        deduplicate_entities_activity,
        find_duplicate_entities_activity,
        merge_entities_activity,
    )


@workflow.defn(name="deduplicate_entities")
class DeduplicateEntitiesWorkflow:
    """Workflow for deduplicating entities in the knowledge graph.

    This workflow orchestrates the entity deduplication process:
    1. Find duplicate entity pairs based on embedding similarity
    2. Merge duplicate pairs preserving relationships
    3. Update affected communities

    The workflow wraps DeduplicateEntitiesTaskHandler logic with
    enterprise-grade orchestration.
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the entity deduplication workflow.

        Args:
            input_data: Deduplication input containing:
                - project_id: Project identifier
                - tenant_id: Tenant identifier
                - task_id: Task log ID for progress tracking
                - threshold: Similarity threshold (0.0-1.0)
                - entity_ids: Optional specific entities to check

        Returns:
            Deduplication result with statistics
        """
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(minutes=10),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        # Execute the main deduplication activity
        result = await workflow.execute_activity(
            deduplicate_entities_activity,
            input_data,
            start_to_close_timeout=timedelta(seconds=1800),
            heartbeat_timeout=timedelta(seconds=120),
            retry_policy=retry_policy,
        )

        return result


@workflow.defn(name="deduplicate_entities_dag")
class DeduplicateEntitiesDAGWorkflow:
    """DAG-based workflow for fine-grained entity deduplication.

    This workflow provides more control over the deduplication pipeline,
    allowing batch processing and progress tracking.
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the DAG-based deduplication workflow.

        Args:
            input_data: Deduplication input containing:
                - project_id: Project identifier
                - tenant_id: Tenant identifier
                - threshold: Similarity threshold (default: 0.85)
                - batch_size: Merge batch size (default: 10)
                - max_pairs: Maximum pairs to process (default: 1000)

        Returns:
            Detailed deduplication result
        """
        project_id = input_data.get("project_id")
        tenant_id = input_data.get("tenant_id")
        threshold = input_data.get("threshold", 0.85)
        batch_size = input_data.get("batch_size", 10)
        max_pairs = input_data.get("max_pairs", 1000)

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(minutes=5),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        # Step 1: Find duplicate pairs
        workflow.logger.info(f"Step 1: Finding duplicates for project {project_id}")
        find_result = await workflow.execute_activity(
            find_duplicate_entities_activity,
            args=[project_id, tenant_id, threshold, max_pairs],
            start_to_close_timeout=timedelta(seconds=600),
            heartbeat_timeout=timedelta(seconds=60),
            retry_policy=retry_policy,
        )

        duplicate_pairs: List[Dict] = find_result.get("duplicate_pairs", [])
        total_pairs = len(duplicate_pairs)
        workflow.logger.info(f"Found {total_pairs} duplicate pairs")

        if not duplicate_pairs:
            return {
                "status": "completed",
                "project_id": project_id,
                "pairs_found": 0,
                "pairs_merged": 0,
            }

        # Step 2: Merge duplicates in batches
        merged_count = 0
        failed_count = 0

        for i in range(0, len(duplicate_pairs), batch_size):
            batch = duplicate_pairs[i : i + batch_size]
            workflow.logger.info(
                f"Step 2: Merging batch {i // batch_size + 1} ({len(batch)} pairs)"
            )

            # Execute batch merges in parallel
            merge_tasks = []
            for pair in batch:
                task = workflow.execute_activity(
                    merge_entities_activity,
                    args=[
                        pair["source_id"],
                        pair["target_id"],
                        project_id,
                        tenant_id,
                    ],
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=retry_policy,
                )
                merge_tasks.append(task)

            # Collect results
            for task in merge_tasks:
                try:
                    await task
                    merged_count += 1
                except Exception as e:
                    workflow.logger.warning(f"Merge failed: {e}")
                    failed_count += 1

        return {
            "status": "completed" if failed_count == 0 else "partial",
            "project_id": project_id,
            "threshold": threshold,
            "pairs_found": total_pairs,
            "pairs_merged": merged_count,
            "pairs_failed": failed_count,
        }


@workflow.defn(name="batch_deduplicate_entities")
class BatchDeduplicateEntitiesWorkflow:
    """Workflow for batch entity deduplication across multiple projects.

    This workflow handles deduplication for multiple projects with:
    - Sequential processing to avoid resource contention
    - Progress tracking per project
    - Partial failure tolerance
    """

    @workflow.run
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute batch entity deduplication.

        Args:
            input_data: Batch input containing:
                - project_ids: List of project IDs to deduplicate
                - tenant_id: Tenant identifier
                - threshold: Similarity threshold

        Returns:
            Batch result with per-project status
        """
        project_ids: List[str] = input_data.get("project_ids", [])
        tenant_id = input_data.get("tenant_id")
        threshold = input_data.get("threshold", 0.85)

        if not project_ids:
            return {"status": "completed", "processed": 0, "results": []}

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(minutes=10),
            maximum_attempts=2,
            backoff_coefficient=2.0,
        )

        results = []
        total_merged = 0

        # Process projects sequentially to avoid Neo4j contention
        for project_id in project_ids:
            workflow.logger.info(f"Processing project: {project_id}")

            try:
                result = await workflow.execute_activity(
                    deduplicate_entities_activity,
                    {
                        "project_id": project_id,
                        "tenant_id": tenant_id,
                        "threshold": threshold,
                    },
                    start_to_close_timeout=timedelta(seconds=1800),
                    heartbeat_timeout=timedelta(seconds=120),
                    retry_policy=retry_policy,
                )

                merged = result.get("merged_count", 0)
                total_merged += merged

                results.append(
                    {
                        "project_id": project_id,
                        "status": "completed",
                        "merged_count": merged,
                    }
                )

            except Exception as e:
                workflow.logger.error(f"Deduplication failed for {project_id}: {e}")
                results.append(
                    {
                        "project_id": project_id,
                        "status": "failed",
                        "error": str(e),
                    }
                )

        succeeded = sum(1 for r in results if r["status"] == "completed")

        return {
            "status": "completed" if succeeded == len(project_ids) else "partial",
            "processed": len(project_ids),
            "succeeded": succeeded,
            "failed": len(project_ids) - succeeded,
            "total_merged": total_merged,
            "results": results,
        }
