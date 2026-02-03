"""Temporal Workflow Engine Adapter for MemStack.

This module implements the WorkflowEnginePort interface using Temporal.io,
providing enterprise-grade workflow orchestration capabilities.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import RetryPolicy

from src.configuration.temporal_config import TemporalSettings, get_temporal_settings
from src.domain.ports.services.workflow_engine_port import (
    WorkflowEnginePort,
    WorkflowExecution,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


class TemporalWorkflowEngine(WorkflowEnginePort):
    """Temporal.io implementation of WorkflowEnginePort.

    This adapter bridges the application layer to Temporal, providing:
    - Workflow lifecycle management
    - Tenant-based task queue isolation
    - Signal support for human-in-the-loop
    - Status monitoring and querying
    """

    # Mapping from Temporal status to WorkflowStatus
    _STATUS_MAP = {
        WorkflowExecutionStatus.RUNNING: WorkflowStatus.RUNNING,
        WorkflowExecutionStatus.COMPLETED: WorkflowStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED: WorkflowStatus.FAILED,
        WorkflowExecutionStatus.CANCELED: WorkflowStatus.CANCELLED,
        WorkflowExecutionStatus.TERMINATED: WorkflowStatus.TERMINATED,
        WorkflowExecutionStatus.TIMED_OUT: WorkflowStatus.TIMED_OUT,
    }

    # Workflow name to class mapping (populated during worker registration)
    _WORKFLOW_REGISTRY: Dict[str, type] = {}

    def __init__(self, client: Client, settings: Optional[TemporalSettings] = None):
        """Initialize the Temporal workflow engine.

        Args:
            client: Connected Temporal client
            settings: Optional Temporal configuration settings
        """
        self._client = client
        self._settings = settings or get_temporal_settings()

    @classmethod
    def register_workflow(cls, workflow_name: str, workflow_class: type) -> None:
        """Register a workflow class for dynamic lookup.

        Args:
            workflow_name: The workflow type name
            workflow_class: The workflow class
        """
        cls._WORKFLOW_REGISTRY[workflow_name] = workflow_class
        logger.debug(f"Registered workflow: {workflow_name}")

    async def start_workflow(
        self,
        workflow_name: str,
        workflow_id: str,
        input_data: Dict[str, Any],
        task_queue: str,
        timeout_seconds: int = 3600,
        metadata: Optional[Dict[str, str]] = None,
    ) -> WorkflowExecution:
        """Start a new workflow execution.

        Args:
            workflow_name: The workflow type name (e.g., "episode_processing")
            workflow_id: Unique identifier for this execution (idempotent key)
            input_data: Input parameters for the workflow
            task_queue: Task queue name for tenant isolation
            timeout_seconds: Maximum workflow execution time
            metadata: Additional metadata (tenant_id, project_id, etc.)

        Returns:
            WorkflowExecution with workflow_id and run_id
        """
        workflow_class = self._get_workflow_class(workflow_name)

        logger.info(
            f"Starting workflow {workflow_name} (id={workflow_id}) "
            f"on queue={task_queue}, timeout={timeout_seconds}s"
        )

        try:
            handle = await self._client.start_workflow(
                workflow_class.run,
                input_data,
                id=workflow_id,
                task_queue=task_queue or self._settings.temporal_default_task_queue,
                execution_timeout=timedelta(seconds=timeout_seconds),
                memo=metadata or {},
            )

            logger.info(f"Started workflow {workflow_id}, run_id={handle.first_execution_run_id}")

            return WorkflowExecution(
                workflow_id=workflow_id,
                run_id=handle.first_execution_run_id or "",
                status=WorkflowStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error(f"Failed to start workflow {workflow_id}: {e}")
            raise

    async def get_workflow_status(self, workflow_id: str) -> WorkflowExecution:
        """Get the current status of a workflow execution.

        Args:
            workflow_id: The workflow identifier

        Returns:
            WorkflowExecution with current status
        """
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            desc = await handle.describe()

            status = self._STATUS_MAP.get(desc.status, WorkflowStatus.RUNNING)

            return WorkflowExecution(
                workflow_id=workflow_id,
                run_id=desc.run_id or "",
                status=status,
                started_at=desc.start_time,
                completed_at=desc.close_time,
            )

        except Exception as e:
            logger.error(f"Failed to get workflow status {workflow_id}: {e}")
            raise

    async def get_workflow_result(
        self, workflow_id: str, timeout_seconds: int = 30
    ) -> Dict[str, Any]:
        """Wait for and get the workflow result.

        Args:
            workflow_id: The workflow identifier
            timeout_seconds: Maximum time to wait for result

        Returns:
            The workflow result data
        """
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            result = await handle.result()
            return result if isinstance(result, dict) else {"result": result}

        except Exception as e:
            logger.error(f"Failed to get workflow result {workflow_id}: {e}")
            raise

    async def cancel_workflow(self, workflow_id: str, reason: Optional[str] = None) -> bool:
        """Cancel a running workflow execution.

        Args:
            workflow_id: The workflow identifier
            reason: Optional cancellation reason

        Returns:
            True if cancellation was successful
        """
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.cancel()

            logger.info(f"Cancelled workflow {workflow_id}, reason: {reason}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel workflow {workflow_id}: {e}")
            return False

    async def terminate_workflow(self, workflow_id: str, reason: Optional[str] = None) -> bool:
        """Forcefully terminate a workflow execution.

        Args:
            workflow_id: The workflow identifier
            reason: Optional termination reason

        Returns:
            True if termination was successful
        """
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.terminate(reason=reason)

            logger.info(f"Terminated workflow {workflow_id}, reason: {reason}")
            return True

        except Exception as e:
            logger.error(f"Failed to terminate workflow {workflow_id}: {e}")
            return False

    async def signal_workflow(
        self, workflow_id: str, signal_name: str, payload: Dict[str, Any]
    ) -> bool:
        """Send a signal to a running workflow.

        Args:
            workflow_id: The workflow identifier
            signal_name: Name of the signal to send
            payload: Signal payload data

        Returns:
            True if signal was sent successfully
        """
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.signal(signal_name, payload)

            logger.info(f"Sent signal {signal_name} to workflow {workflow_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to signal workflow {workflow_id}: {e}")
            return False

    async def list_workflows(
        self,
        task_queue: Optional[str] = None,
        status: Optional[WorkflowStatus] = None,
        limit: int = 100,
    ) -> list[WorkflowExecution]:
        """List workflow executions with optional filtering.

        Args:
            task_queue: Filter by task queue (tenant isolation)
            status: Filter by workflow status
            limit: Maximum number of results

        Returns:
            List of workflow executions
        """
        # Build query string
        query_parts = []
        if task_queue:
            query_parts.append(f'TaskQueue="{task_queue}"')
        if status:
            # Map WorkflowStatus back to Temporal status name
            temporal_status = status.value
            query_parts.append(f'ExecutionStatus="{temporal_status}"')

        query = " AND ".join(query_parts) if query_parts else None

        try:
            results = []
            async for workflow in self._client.list_workflows(query=query):
                if len(results) >= limit:
                    break

                exec_status = self._STATUS_MAP.get(workflow.status, WorkflowStatus.RUNNING)

                results.append(
                    WorkflowExecution(
                        workflow_id=workflow.id,
                        run_id=workflow.run_id or "",
                        status=exec_status,
                        started_at=workflow.start_time,
                        completed_at=workflow.close_time,
                    )
                )

            return results

        except Exception as e:
            logger.error(f"Failed to list workflows: {e}")
            raise

    def _get_workflow_class(self, workflow_name: str) -> type:
        """Get workflow class by name.

        Args:
            workflow_name: The workflow type name

        Returns:
            The workflow class

        Raises:
            ValueError: If workflow is not registered
        """
        if workflow_name in self._WORKFLOW_REGISTRY:
            return self._WORKFLOW_REGISTRY[workflow_name]

        # Lazy import workflow classes
        from src.infrastructure.adapters.secondary.temporal.workflows import (
            community,
            entity,
            episode,
            project_agent_workflow,
        )

        # Register default workflows
        mapping = {
            "episode_processing": episode.EpisodeProcessingWorkflow,
            "rebuild_communities": community.RebuildCommunitiesWorkflow,
            "deduplicate_entities": entity.DeduplicateEntitiesWorkflow,
            "incremental_refresh": episode.IncrementalRefreshWorkflow,
            "project_agent": project_agent_workflow.ProjectAgentWorkflow,
        }

        if workflow_name not in mapping:
            raise ValueError(f"Unknown workflow type: {workflow_name}")

        # Cache for future use
        self._WORKFLOW_REGISTRY[workflow_name] = mapping[workflow_name]
        return mapping[workflow_name]

    def get_default_retry_policy(self) -> RetryPolicy:
        """Get the default retry policy for activities.

        Returns:
            Configured RetryPolicy
        """
        return RetryPolicy(
            initial_interval=timedelta(seconds=self._settings.temporal_initial_retry_interval),
            maximum_interval=timedelta(seconds=self._settings.temporal_max_retry_interval),
            maximum_attempts=self._settings.temporal_max_retry_attempts,
            backoff_coefficient=self._settings.temporal_retry_backoff_coefficient,
        )
