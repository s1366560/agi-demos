"""Workflow Engine Port - Abstract interface for workflow orchestration.

This port defines the contract for workflow engines (Temporal, Conductor, etc.)
following the hexagonal architecture pattern.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class WorkflowStatus(str, Enum):
    """Workflow execution status."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"
    TIMED_OUT = "TIMED_OUT"


@dataclass
class WorkflowExecution:
    """Workflow execution result."""

    workflow_id: str
    run_id: str
    status: WorkflowStatus
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WorkflowEnginePort(ABC):
    """Abstract port for workflow engine operations.

    This interface allows the application layer to work with different
    workflow orchestration engines (Temporal, Conductor, etc.) without
    coupling to specific implementations.
    """

    @abstractmethod
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
        pass

    @abstractmethod
    async def get_workflow_status(self, workflow_id: str) -> WorkflowExecution:
        """Get the current status of a workflow execution.

        Args:
            workflow_id: The workflow identifier

        Returns:
            WorkflowExecution with current status
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def cancel_workflow(self, workflow_id: str, reason: Optional[str] = None) -> bool:
        """Cancel a running workflow execution.

        Args:
            workflow_id: The workflow identifier
            reason: Optional cancellation reason

        Returns:
            True if cancellation was successful
        """
        pass

    @abstractmethod
    async def terminate_workflow(self, workflow_id: str, reason: Optional[str] = None) -> bool:
        """Forcefully terminate a workflow execution.

        Unlike cancel, terminate immediately stops the workflow without
        giving it a chance to handle the cancellation.

        Args:
            workflow_id: The workflow identifier
            reason: Optional termination reason

        Returns:
            True if termination was successful
        """
        pass

    @abstractmethod
    async def signal_workflow(
        self, workflow_id: str, signal_name: str, payload: Dict[str, Any]
    ) -> bool:
        """Send a signal to a running workflow.

        Signals allow external events to influence workflow execution,
        useful for human-in-the-loop scenarios.

        Args:
            workflow_id: The workflow identifier
            signal_name: Name of the signal to send
            payload: Signal payload data

        Returns:
            True if signal was sent successfully
        """
        pass

    @abstractmethod
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
        pass
