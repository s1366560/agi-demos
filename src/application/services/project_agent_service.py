"""
Project Agent Service - Application layer service for project-level agents.

This service provides a clean interface for managing project-level ReActAgent
instances through Temporal workflows. It handles:

1. Lifecycle Management:
   - Starting project agent workflows
   - Stopping project agent workflows
   - Querying project agent status

2. Chat Execution:
   - Sending chat requests to project agents
   - Streaming responses
   - Error handling and recovery

3. Resource Management:
   - Listing active project agents
   - Monitoring health status
   - Cleanup of idle agents

Usage:
    service = ProjectAgentService(temporal_client)

    # Start project agent
    await service.start_project_agent(
        tenant_id="tenant-123",
        project_id="project-456"
    )

    # Send chat request
    result = await service.chat(
        tenant_id="tenant-123",
        project_id="project-456",
        conversation_id="conv-789",
        user_message="Hello"
    )

    # Get status
    status = await service.get_status(
        tenant_id="tenant-123",
        project_id="project-456"
    )

    # Stop project agent
    await service.stop_project_agent(
        tenant_id="tenant-123",
        project_id="project-456"
    )
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
    ProjectAgentWorkflow,
    ProjectAgentWorkflowInput,
    ProjectAgentWorkflowStatus,
    ProjectChatRequest,
    ProjectChatResult,
    get_project_agent_workflow_id,
)

logger = logging.getLogger(__name__)


@dataclass
class ProjectAgentStartOptions:
    """Options for starting a project agent."""

    tenant_id: str
    project_id: str
    agent_mode: str = "default"

    # LLM Configuration
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_steps: int = 20

    # Session Configuration
    # Note: Agent now runs persistently until explicitly stopped
    persistent: bool = True  # Agent runs forever until explicitly stopped
    max_concurrent_chats: int = 10

    # Task Queue
    task_queue: str = "project-agent-tasks"

    # Behavior
    wait_for_ready: bool = True
    timeout_seconds: float = 60.0


@dataclass
class ProjectAgentChatOptions:
    """Options for sending a chat request to a project agent."""

    tenant_id: str
    project_id: str
    conversation_id: str
    message_id: str
    user_message: str
    user_id: str

    agent_mode: str = "default"
    conversation_context: Optional[List[Dict[str, Any]]] = None

    # Runtime overrides
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_steps: Optional[int] = None

    # Timeout
    timeout_seconds: float = 600.0


@dataclass
class ProjectAgentInfo:
    """Information about a project agent."""

    tenant_id: str
    project_id: str
    agent_mode: str
    workflow_id: str

    is_running: bool = False
    is_initialized: bool = False
    is_active: bool = False

    total_chats: int = 0
    active_chats: int = 0
    failed_chats: int = 0

    tool_count: int = 0
    skill_count: int = 0

    uptime_seconds: float = 0.0
    last_activity_at: Optional[str] = None


class ProjectAgentService:
    """
    Service for managing project-level agent workflows.

    This service provides high-level operations for project agent lifecycle
    management, abstracting the Temporal workflow details.
    """

    DEFAULT_TASK_QUEUE = "project-agent-tasks"

    def __init__(self, temporal_client: Client):
        """
        Initialize the project agent service.

        Args:
            temporal_client: Connected Temporal client
        """
        self._client = temporal_client

    async def start_project_agent(
        self,
        options: ProjectAgentStartOptions,
    ) -> ProjectAgentInfo:
        """
        Start a project agent workflow.

        If the workflow already exists, it will return info about the
        existing workflow instead of raising an error.

        Args:
            options: Start options

        Returns:
            Project agent information
        """
        workflow_id = get_project_agent_workflow_id(
            options.tenant_id,
            options.project_id,
            options.agent_mode,
        )

        input_data = ProjectAgentWorkflowInput(
            tenant_id=options.tenant_id,
            project_id=options.project_id,
            agent_mode=options.agent_mode,
            model=options.model,
            api_key=options.api_key,
            base_url=options.base_url,
            temperature=options.temperature,
            max_tokens=options.max_tokens,
            max_steps=options.max_steps,
            persistent=options.persistent,
            max_concurrent_chats=options.max_concurrent_chats,
        )

        try:
            # Start the workflow
            handle = await self._client.start_workflow(
                ProjectAgentWorkflow.run,
                input_data,
                id=workflow_id,
                task_queue=options.task_queue or self.DEFAULT_TASK_QUEUE,
                execution_timeout=timedelta(hours=24),  # Long-running
            )

            logger.info(
                f"ProjectAgentService: Started workflow {workflow_id} "
                f"for project {options.project_id}"
            )

            # Wait for initialization if requested
            if options.wait_for_ready:
                try:
                    # Poll for initialization status
                    async for attempt in self._poll_with_timeout(
                        timeout_seconds=options.timeout_seconds,
                        interval_seconds=1.0,
                    ):
                        status = await handle.query(ProjectAgentWorkflow.get_status)
                        if status.is_initialized:
                            break
                except TimeoutError:
                    logger.warning(
                        f"ProjectAgentService: Timeout waiting for {workflow_id} to initialize"
                    )

            # Get current status
            return await self._get_info_from_handle(handle, options)

        except WorkflowAlreadyStartedError:
            # Workflow already exists, return existing info
            logger.info(
                f"ProjectAgentService: Workflow {workflow_id} already exists, "
                "returning existing info"
            )

            handle = self._client.get_workflow_handle(workflow_id)
            return await self._get_info_from_handle(handle, options)

    async def stop_project_agent(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
        graceful: bool = True,
        timeout_seconds: float = 30.0,
    ) -> bool:
        """
        Stop a project agent workflow.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode
            graceful: Whether to wait for graceful shutdown
            timeout_seconds: Timeout for graceful shutdown

        Returns:
            True if stopped successfully
        """
        workflow_id = get_project_agent_workflow_id(tenant_id, project_id, agent_mode)

        try:
            handle = self._client.get_workflow_handle(workflow_id)

            # Send stop signal
            await handle.signal(ProjectAgentWorkflow.stop)

            if graceful:
                try:
                    # Wait for workflow to complete
                    await handle.result(timeout=timedelta(seconds=timeout_seconds))
                except Exception as e:
                    logger.warning(
                        f"ProjectAgentService: Graceful stop timeout for {workflow_id}: {e}"
                    )
                    # Force terminate
                    await handle.terminate("Force stop after timeout")

            logger.info(f"ProjectAgentService: Stopped workflow {workflow_id}")
            return True

        except Exception as e:
            logger.error(f"ProjectAgentService: Error stopping {workflow_id}: {e}")
            return False

    async def pause_project_agent(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> bool:
        """
        Pause a project agent (prevents new chats).

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode

        Returns:
            True if paused successfully
        """
        workflow_id = get_project_agent_workflow_id(tenant_id, project_id, agent_mode)

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.signal(ProjectAgentWorkflow.pause)
            logger.info(f"ProjectAgentService: Paused workflow {workflow_id}")
            return True
        except Exception as e:
            logger.error(f"ProjectAgentService: Error pausing {workflow_id}: {e}")
            return False

    async def resume_project_agent(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> bool:
        """
        Resume a paused project agent.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode

        Returns:
            True if resumed successfully
        """
        workflow_id = get_project_agent_workflow_id(tenant_id, project_id, agent_mode)

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.signal(ProjectAgentWorkflow.resume)
            logger.info(f"ProjectAgentService: Resumed workflow {workflow_id}")
            return True
        except Exception as e:
            logger.error(f"ProjectAgentService: Error resuming {workflow_id}: {e}")
            return False

    async def refresh_project_agent(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> bool:
        """
        Refresh a project agent (reload tools, clear caches).

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode

        Returns:
            True if refresh requested successfully
        """
        workflow_id = get_project_agent_workflow_id(tenant_id, project_id, agent_mode)

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            result = await handle.execute_update(ProjectAgentWorkflow.refresh)
            logger.info(f"ProjectAgentService: Refreshed workflow {workflow_id}: {result}")
            return True
        except Exception as e:
            logger.error(f"ProjectAgentService: Error refreshing {workflow_id}: {e}")
            return False

    async def chat(
        self,
        options: ProjectAgentChatOptions,
    ) -> ProjectChatResult:
        """
        Send a chat request to a project agent.

        This method sends a chat request to the project agent workflow
        and returns the result.

        Args:
            options: Chat options

        Returns:
            Chat result
        """
        workflow_id = get_project_agent_workflow_id(
            options.tenant_id,
            options.project_id,
            options.agent_mode,
        )

        handle = self._client.get_workflow_handle(workflow_id)

        # Check if workflow is running
        try:
            status = await handle.query(ProjectAgentWorkflow.get_status)
            if not status.is_initialized:
                logger.warning(f"ProjectAgentService: Workflow {workflow_id} not initialized")
                return ProjectChatResult(
                    conversation_id=options.conversation_id,
                    message_id=options.message_id,
                    is_error=True,
                    error_message="Project agent not initialized",
                )
        except Exception as e:
            logger.warning(f"ProjectAgentService: Error querying status for {workflow_id}: {e}")
            # Try to start the workflow
            await self.start_project_agent(
                ProjectAgentStartOptions(
                    tenant_id=options.tenant_id,
                    project_id=options.project_id,
                    agent_mode=options.agent_mode,
                )
            )

        # Build chat request
        request = ProjectChatRequest(
            conversation_id=options.conversation_id,
            message_id=options.message_id,
            user_message=options.user_message,
            user_id=options.user_id,
            conversation_context=options.conversation_context or [],
            temperature=options.temperature,
            max_tokens=options.max_tokens,
            max_steps=options.max_steps,
        )

        try:
            # Execute chat update
            result = await handle.execute_update(
                ProjectAgentWorkflow.chat,
                request,
            )
            return result

        except Exception as e:
            logger.error(f"ProjectAgentService: Chat error for {workflow_id}: {e}")
            return ProjectChatResult(
                conversation_id=options.conversation_id,
                message_id=options.message_id,
                is_error=True,
                error_message=str(e),
            )

    async def get_status(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> Optional[ProjectAgentWorkflowStatus]:
        """
        Get the status of a project agent.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode

        Returns:
            Project agent status or None if not found
        """
        workflow_id = get_project_agent_workflow_id(tenant_id, project_id, agent_mode)

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            status = await handle.query(ProjectAgentWorkflow.get_status)
            return status
        except Exception as e:
            logger.debug(f"ProjectAgentService: Error getting status for {workflow_id}: {e}")
            return None

    async def get_metrics(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get metrics for a project agent.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode

        Returns:
            Metrics dictionary or None if not found
        """
        workflow_id = get_project_agent_workflow_id(tenant_id, project_id, agent_mode)

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            metrics = await handle.query(ProjectAgentWorkflow.get_metrics)
            return {
                "total_requests": metrics.total_requests,
                "successful_requests": metrics.successful_requests,
                "failed_requests": metrics.failed_requests,
                "avg_latency_ms": metrics.avg_latency_ms,
                "p95_latency_ms": metrics.p95_latency_ms,
                "p99_latency_ms": metrics.p99_latency_ms,
                "tool_execution_count": metrics.tool_execution_count,
            }
        except Exception as e:
            logger.debug(f"ProjectAgentService: Error getting metrics for {workflow_id}: {e}")
            return None

    async def list_project_agents(
        self,
        tenant_id: Optional[str] = None,
    ) -> List[ProjectAgentInfo]:
        """
        List all project agents.

        Note: This queries Temporal for workflows. It may be slow for
        large numbers of workflows.

        Args:
            tenant_id: Optional tenant filter

        Returns:
            List of project agent information
        """
        # Build query
        if tenant_id:
            query = f'WorkflowType="project_agent" AND WorkflowId STARTS WITH "project_agent_{tenant_id}_"'
        else:
            query = 'WorkflowType="project_agent"'

        results = []

        try:
            async for workflow in self._client.list_workflows(query=query):
                # Parse workflow ID to extract info
                # Format: project_agent_{tenant_id}_{project_id}_{agent_mode}
                parts = workflow.id.split("_")
                if len(parts) >= 4:
                    agent_tenant_id = parts[2]
                    agent_project_id = parts[3]
                    agent_mode = parts[4] if len(parts) > 4 else "default"

                    info = ProjectAgentInfo(
                        tenant_id=agent_tenant_id,
                        project_id=agent_project_id,
                        agent_mode=agent_mode,
                        workflow_id=workflow.id,
                        is_running=workflow.status == 1,  # WORKFLOW_EXECUTION_STATUS_RUNNING
                    )
                    results.append(info)

        except Exception as e:
            logger.error(f"ProjectAgentService: Error listing workflows: {e}")

        return results

    async def is_project_agent_running(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> bool:
        """
        Check if a project agent is running.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode

        Returns:
            True if running
        """
        workflow_id = get_project_agent_workflow_id(tenant_id, project_id, agent_mode)

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            desc = await handle.describe()
            return desc.status == 1  # WORKFLOW_EXECUTION_STATUS_RUNNING
        except Exception:
            return False

    async def _get_info_from_handle(
        self,
        handle: Any,
        options: ProjectAgentStartOptions,
    ) -> ProjectAgentInfo:
        """Build ProjectAgentInfo from workflow handle."""
        workflow_id = handle.id

        try:
            status = await handle.query(ProjectAgentWorkflow.get_status)
            return ProjectAgentInfo(
                tenant_id=options.tenant_id,
                project_id=options.project_id,
                agent_mode=options.agent_mode,
                workflow_id=workflow_id,
                is_running=True,
                is_initialized=status.is_initialized,
                is_active=status.is_active,
                total_chats=status.total_chats,
                active_chats=status.active_chats,
                failed_chats=status.failed_chats,
                tool_count=status.tool_count,
                skill_count=status.skill_count,
                uptime_seconds=status.uptime_seconds,
                last_activity_at=status.last_activity_at,
            )
        except Exception as e:
            logger.debug(f"Error getting info from handle: {e}")
            return ProjectAgentInfo(
                tenant_id=options.tenant_id,
                project_id=options.project_id,
                agent_mode=options.agent_mode,
                workflow_id=workflow_id,
                is_running=True,
            )

    async def _poll_with_timeout(
        self,
        timeout_seconds: float,
        interval_seconds: float = 1.0,
    ):
        """Async generator for polling with timeout."""
        import asyncio

        start_time = asyncio.get_event_loop().time()

        while True:
            current_time = asyncio.get_event_loop().time()
            if current_time - start_time > timeout_seconds:
                raise TimeoutError(f"Polling timed out after {timeout_seconds}s")

            yield True
            await asyncio.sleep(interval_seconds)
