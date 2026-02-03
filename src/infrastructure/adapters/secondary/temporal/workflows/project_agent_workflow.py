"""
Project-Level Agent Session Workflow for Temporal.

This module provides a persistent Temporal Workflow that manages a
project-level ReAct Agent instance. Each project has its own long-running
workflow that maintains state across multiple chat requests.

Workflow ID pattern: project_agent_{tenant_id}_{project_id}_{agent_mode}

Key Features:
- Project-scoped agent lifecycle management
- Persistent agent instance across requests
- Independent configuration per project
- Resource isolation between projects
- Graceful shutdown and recovery

Usage:
    # Start project agent workflow
    handle = await client.start_workflow(
        ProjectAgentWorkflow.run,
        ProjectAgentWorkflowInput(
            tenant_id="tenant-123",
            project_id="project-456",
            agent_mode="default",
        ),
        id=f"project_agent_tenant-123_project-456_default",
        task_queue="project-agent-tasks",
    )

    # Send chat request
    result = await handle.execute_update(
        ProjectAgentWorkflow.chat,
        ProjectChatRequest(
            conversation_id="conv-789",
            message_id="msg-abc",
            user_message="Hello",
            user_id="user-xyz",
        ),
    )

    # Query status
    status = await handle.query(ProjectAgentWorkflow.get_status)

    # Stop workflow
    await handle.signal(ProjectAgentWorkflow.stop)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import workflow-safe types
with workflow.unsafe.imports_passed_through():
    from src.infrastructure.agent.core.project_react_agent import (
        ProjectAgentConfig,
    )

logger = logging.getLogger(__name__)


@dataclass
class ProjectAgentWorkflowInput:
    """Input for starting a Project Agent Workflow."""

    tenant_id: str
    project_id: str
    agent_mode: str = "default"

    # Agent Configuration
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_steps: int = 20

    # Session Configuration
    # Note: persistent=True means the workflow runs indefinitely until explicitly stopped
    persistent: bool = True  # Agent runs forever until explicitly stopped
    idle_timeout_seconds: int = 3600  # 1 hour idle timeout
    max_concurrent_chats: int = 10

    # Tool Configuration
    mcp_tools_ttl_seconds: int = 300  # 5 minutes

    # Feature Flags
    enable_skills: bool = True
    enable_subagents: bool = True


@dataclass
class ProjectChatRequest:
    """Request to send a chat message to the project agent."""

    conversation_id: str
    message_id: str
    user_message: str
    user_id: str

    # Conversation context (last N messages)
    conversation_context: List[Dict[str, Any]] = field(default_factory=list)

    # Attachment IDs for this message
    attachment_ids: Optional[List[str]] = None

    # Optional configuration overrides for this request
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_steps: Optional[int] = None


@dataclass
class ProjectChatResult:
    """Result from a project agent chat request."""

    conversation_id: str
    message_id: str
    content: str = ""
    sequence_number: int = 0
    is_error: bool = False
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    event_count: int = 0


@dataclass
class ProjectAgentWorkflowStatus:
    """Status information for the project agent workflow."""

    tenant_id: str
    project_id: str
    agent_mode: str
    workflow_id: str

    is_initialized: bool = False
    is_active: bool = True
    is_executing: bool = False

    total_chats: int = 0
    active_chats: int = 0
    failed_chats: int = 0

    tool_count: int = 0
    skill_count: int = 0

    created_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    uptime_seconds: float = 0.0

    # Current execution info
    current_conversation_id: Optional[str] = None
    current_message_id: Optional[str] = None


@dataclass
class ProjectAgentMetrics:
    """Detailed metrics for the project agent."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    tool_execution_count: Dict[str, int] = field(default_factory=dict)


@workflow.defn(name="project_agent")
class ProjectAgentWorkflow:
    """
    Long-running Workflow for managing a project-level Agent Session.

    This workflow maintains a persistent ReActAgent instance for a specific
    project, enabling:
    - Fast response times (no reinitialization per request)
    - Project-scoped resource caching
    - Independent lifecycle per project
    - Resource isolation between projects

    The workflow stays alive until:
    - Explicit stop signal received
    - Idle timeout exceeded
    - Fatal error occurs

    Workflow ID pattern: project_agent_{tenant_id}_{project_id}_{agent_mode}
    """

    def __init__(self):
        """Initialize workflow state."""
        self._input: Optional[ProjectAgentWorkflowInput] = None
        self._workflow_id: str = ""

        # Control flags
        self._stop_requested = False
        self._pause_requested = False
        self._refresh_requested = False

        # State tracking
        self._initialized = False
        self._error: Optional[str] = None
        self._created_at: Optional[str] = None

        # Execution tracking
        self._total_chats = 0
        self._failed_chats = 0
        self._active_chats = 0
        self._current_conversation_id: Optional[str] = None
        self._current_message_id: Optional[str] = None

        # Metrics
        self._latencies: List[float] = []
        self._tool_executions: Dict[str, int] = {}

        # Recovery tracking
        self._recovery_attempts = 0
        self._max_recovery_attempts = 3

    def _should_attempt_recovery(self, error_message: str) -> bool:
        """Check if automatic recovery should be attempted."""
        if self._recovery_attempts >= self._max_recovery_attempts:
            return False

        recoverable_patterns = [
            "session",
            "cache",
            "not found",
            "expired",
            "invalid",
            "connection",
            "timeout",
        ]

        error_lower = error_message.lower()
        return any(pattern in error_lower for pattern in recoverable_patterns)

    @workflow.run
    async def run(self, input: ProjectAgentWorkflowInput) -> Dict[str, Any]:
        """
        Main workflow execution - stays alive until stop signal or timeout.

        Args:
            input: Workflow input configuration

        Returns:
            Final workflow status
        """
        self._input = input
        self._workflow_id = workflow.info().workflow_id
        self._created_at = workflow.now().isoformat()

        workflow.logger.info(
            f"Starting ProjectAgentWorkflow: tenant={input.tenant_id}, "
            f"project={input.project_id}, mode={input.agent_mode}, "
            f"workflow_id={self._workflow_id}"
        )

        # Main lifecycle loop
        while not self._stop_requested:
            try:
                # Initialize or refresh agent
                if not self._initialized or self._refresh_requested:
                    success = await self._initialize_agent()
                    if not success:
                        self._error = "Failed to initialize agent"
                        break

                # Wait for activity (chat requests, signals, or timeout)
                await self._wait_for_activity()

            except asyncio.TimeoutError:
                # Idle timeout - normal shutdown
                workflow.logger.info(f"ProjectAgentWorkflow idle timeout: {self._workflow_id}")
                self._stop_requested = True

            except Exception as e:
                workflow.logger.error(f"ProjectAgentWorkflow error: {type(e).__name__}: {e}")
                self._error = str(e)

                # Check for recovery
                if self._should_attempt_recovery(str(e)):
                    self._recovery_attempts += 1
                    workflow.logger.warning(
                        f"Attempting recovery ({self._recovery_attempts}/"
                        f"{self._max_recovery_attempts})"
                    )
                    self._initialized = False
                    self._refresh_requested = True
                    continue
                else:
                    break

        # Cleanup before exit
        await self._cleanup()

        return self._build_final_status()

    async def _initialize_agent(self) -> bool:
        """Initialize the project agent via activity."""
        with workflow.unsafe.imports_passed_through():
            from src.infrastructure.adapters.secondary.temporal.activities.project_agent import (
                initialize_project_agent_activity,
            )

        workflow.logger.info(f"Initializing project agent: {self._workflow_id}")

        config = ProjectAgentConfig(
            tenant_id=self._input.tenant_id,
            project_id=self._input.project_id,
            agent_mode=self._input.agent_mode,
            model=self._input.model,
            api_key=self._input.api_key,
            base_url=self._input.base_url,
            temperature=self._input.temperature,
            max_tokens=self._input.max_tokens,
            max_steps=self._input.max_steps,
            idle_timeout_seconds=self._input.idle_timeout_seconds,
            max_concurrent_chats=self._input.max_concurrent_chats,
            mcp_tools_ttl_seconds=self._input.mcp_tools_ttl_seconds,
            enable_skills=self._input.enable_skills,
            enable_subagents=self._input.enable_subagents,
        )

        # Force refresh if requested
        force_refresh = self._refresh_requested
        self._refresh_requested = False

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        try:
            result = await workflow.execute_activity(
                initialize_project_agent_activity,
                {
                    "config": config,
                    "force_refresh": force_refresh,
                },
                start_to_close_timeout=timedelta(seconds=120),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=retry_policy,
            )

            if result.get("status") == "initialized":
                self._initialized = True
                self._error = None
                self._recovery_attempts = 0

                # Update state from result
                self._tool_count = result.get("tool_count", 0)
                self._skill_count = result.get("skill_count", 0)

                workflow.logger.info(
                    f"Project agent initialized: tools={self._tool_count}, "
                    f"skills={self._skill_count}"
                )
                return True
            else:
                self._error = result.get("error", "Unknown initialization error")
                workflow.logger.error(f"Project agent initialization failed: {self._error}")
                return False

        except Exception as e:
            self._error = str(e)
            workflow.logger.error(f"Project agent initialization exception: {e}")
            return False

    async def _wait_for_activity(self) -> None:
        """Wait for chat requests, signals (persistent mode - no timeout)."""
        # Reset pause flag
        was_paused = self._pause_requested
        self._pause_requested = False

        if was_paused:
            # If was paused, wait indefinitely until stop or chat
            workflow.logger.info("Project agent paused, waiting for resume or stop")
            await workflow.wait_condition(lambda: self._stop_requested or self._active_chats > 0)
        else:
            # Persistent mode - wait indefinitely for signals
            # No idle timeout - workflow runs forever until explicitly stopped
            workflow.logger.info("Project agent running (persistent mode)")
            await workflow.wait_condition(
                lambda: self._stop_requested or self._pause_requested or self._refresh_requested,
            )

    async def _cleanup(self) -> None:
        """Cleanup resources before workflow exit."""
        with workflow.unsafe.imports_passed_through():
            from src.infrastructure.adapters.secondary.temporal.activities.project_agent import (
                cleanup_project_agent_activity,
            )

        workflow.logger.info(f"Cleaning up project agent: {self._workflow_id}")

        try:
            await workflow.execute_activity(
                cleanup_project_agent_activity,
                {
                    "tenant_id": self._input.tenant_id,
                    "project_id": self._input.project_id,
                    "agent_mode": self._input.agent_mode,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as e:
            workflow.logger.warning(f"Project agent cleanup error: {e}")

    def _build_final_status(self) -> Dict[str, Any]:
        """Build final workflow status."""
        uptime_seconds = 0.0
        if self._created_at:
            uptime_seconds = (
                workflow.now() - workflow.datetime.fromisoformat(self._created_at)
            ).total_seconds()

        return {
            "tenant_id": self._input.tenant_id,
            "project_id": self._input.project_id,
            "agent_mode": self._input.agent_mode,
            "workflow_id": self._workflow_id,
            "status": "stopped" if not self._error else "error",
            "total_chats": self._total_chats,
            "failed_chats": self._failed_chats,
            "uptime_seconds": uptime_seconds,
            "error": self._error,
        }

    @workflow.update
    async def chat(self, request: ProjectChatRequest) -> ProjectChatResult:
        """
        Handle a chat request.

        This update handler executes a chat and returns the result.
        Uses Temporal's update mechanism for synchronous request-response.

        Args:
            request: Chat request containing message and context

        Returns:
            Chat result with content and metadata
        """
        if not self._initialized:
            return ProjectChatResult(
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                is_error=True,
                error_message="Project agent not initialized",
            )

        if self._pause_requested:
            return ProjectChatResult(
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                is_error=True,
                error_message="Project agent is paused",
            )

        # Track execution
        self._active_chats += 1
        self._current_conversation_id = request.conversation_id
        self._current_message_id = request.message_id

        workflow.logger.info(
            f"Processing chat: conversation={request.conversation_id}, message={request.message_id}"
        )

        try:
            with workflow.unsafe.imports_passed_through():
                from src.infrastructure.adapters.secondary.temporal.activities.project_agent import (
                    execute_project_chat_activity,
                )

            # Build config with optional overrides
            config = {
                "tenant_id": self._input.tenant_id,
                "project_id": self._input.project_id,
                "agent_mode": self._input.agent_mode,
                "model": self._input.model,
                "temperature": request.temperature or self._input.temperature,
                "max_tokens": request.max_tokens or self._input.max_tokens,
                "max_steps": request.max_steps or self._input.max_steps,
            }

            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_attempts=2,
                backoff_coefficient=2.0,
            )

            result = await workflow.execute_activity(
                execute_project_chat_activity,
                {
                    "conversation_id": request.conversation_id,
                    "message_id": request.message_id,
                    "user_message": request.user_message,
                    "user_id": request.user_id,
                    "conversation_context": request.conversation_context,
                    "config": config,
                },
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            # Update metrics
            self._total_chats += 1
            if result.get("is_error"):
                self._failed_chats += 1

            # Track latency
            execution_time_ms = result.get("execution_time_ms", 0)
            self._latencies.append(execution_time_ms)
            if len(self._latencies) > 100:
                self._latencies = self._latencies[-100:]

            return ProjectChatResult(
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                content=result.get("content", ""),
                sequence_number=result.get("sequence_number", 0),
                is_error=result.get("is_error", False),
                error_message=result.get("error_message"),
                execution_time_ms=execution_time_ms,
                event_count=result.get("event_count", 0),
            )

        except Exception as e:
            workflow.logger.error(f"Chat execution failed: {e}")
            self._failed_chats += 1

            # Attempt recovery on session-related errors
            error_msg = str(e)
            if self._should_attempt_recovery(error_msg):
                workflow.logger.warning(f"Attempting recovery after error: {error_msg}")
                self._initialized = False  # Will trigger re-initialization

            return ProjectChatResult(
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                is_error=True,
                error_message=error_msg,
            )

        finally:
            self._active_chats -= 1
            if self._active_chats == 0:
                self._current_conversation_id = None
                self._current_message_id = None

    @workflow.update
    async def refresh(self) -> Dict[str, Any]:
        """
        Refresh the project agent (reload tools, clear caches).

        Returns:
            Refresh result
        """
        workflow.logger.info(f"Refreshing project agent: {self._workflow_id}")

        self._refresh_requested = True
        self._initialized = False

        # Wait for re-initialization
        # In the next loop iteration, _initialize_agent will be called

        return {
            "status": "refresh_requested",
            "workflow_id": self._workflow_id,
        }

    @workflow.query
    def get_status(self) -> ProjectAgentWorkflowStatus:
        """
        Query current workflow status.

        Returns:
            Current status information
        """
        uptime_seconds = 0.0
        if self._created_at:
            try:
                created_time = workflow.datetime.fromisoformat(self._created_at)
                uptime_seconds = (workflow.now() - created_time).total_seconds()
            except Exception:
                pass

        return ProjectAgentWorkflowStatus(
            tenant_id=self._input.tenant_id if self._input else "",
            project_id=self._input.project_id if self._input else "",
            agent_mode=self._input.agent_mode if self._input else "",
            workflow_id=self._workflow_id,
            is_initialized=self._initialized,
            is_active=not self._stop_requested and not self._pause_requested,
            is_executing=self._active_chats > 0,
            total_chats=self._total_chats,
            active_chats=self._active_chats,
            failed_chats=self._failed_chats,
            tool_count=getattr(self, "_tool_count", 0),
            skill_count=getattr(self, "_skill_count", 0),
            created_at=self._created_at,
            last_activity_at=None,  # Could track this
            uptime_seconds=uptime_seconds,
            current_conversation_id=self._current_conversation_id,
            current_message_id=self._current_message_id,
        )

    @workflow.query
    def get_metrics(self) -> ProjectAgentMetrics:
        """
        Query detailed metrics.

        Returns:
            Metrics dictionary
        """
        avg_latency = 0.0
        p95_latency = 0.0
        p99_latency = 0.0

        if self._latencies:
            sorted_latencies = sorted(self._latencies)
            n = len(sorted_latencies)
            avg_latency = sum(sorted_latencies) / n
            p95_latency = sorted_latencies[int(n * 0.95)] if n >= 20 else sorted_latencies[-1]
            p99_latency = sorted_latencies[int(n * 0.99)] if n >= 100 else sorted_latencies[-1]

        successful = self._total_chats - self._failed_chats

        return ProjectAgentMetrics(
            total_requests=self._total_chats,
            successful_requests=successful,
            failed_requests=self._failed_chats,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            tool_execution_count=dict(self._tool_executions),
        )

    @workflow.signal
    def stop(self):
        """Signal to stop the project agent workflow."""
        workflow.logger.info(f"Received stop signal: {self._workflow_id}")
        self._stop_requested = True

    @workflow.signal
    def pause(self):
        """Signal to pause the project agent (prevent new chats)."""
        workflow.logger.info(f"Received pause signal: {self._workflow_id}")
        self._pause_requested = True

    @workflow.signal
    def resume(self):
        """Signal to resume a paused project agent."""
        workflow.logger.info(f"Received resume signal: {self._workflow_id}")
        self._pause_requested = False

    @workflow.signal
    def extend_timeout(self, additional_seconds: int = 1800):
        """
        Signal to extend the idle timeout.

        Args:
            additional_seconds: Additional seconds
        """
        workflow.logger.info(f"Extending timeout by {additional_seconds}s: {self._workflow_id}")
        # This signal resets activity by triggering a new wait
        # The actual implementation would track extended timeout separately

    @workflow.signal
    def restart(self):
        """
        Signal to restart the project agent.

        This signal sets a stop flag that will cause the workflow to
        stop. The caller is responsible for starting a new workflow instance.
        """
        workflow.logger.info(f"Received restart signal: {self._workflow_id}")
        self._stop_requested = True
        # Mark as restart (not error) for proper status reporting
        self._error = None


def get_project_agent_workflow_id(
    tenant_id: str,
    project_id: str,
    agent_mode: str = "default",
) -> str:
    """
    Generate the workflow ID for a Project Agent.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        agent_mode: Agent mode

    Returns:
        Workflow ID string
    """
    return f"project_agent_{tenant_id}_{project_id}_{agent_mode}"
