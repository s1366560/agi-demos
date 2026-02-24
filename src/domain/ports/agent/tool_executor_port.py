"""
Tool Executor Port - Domain interface for tool execution.

Defines the contract for executing agent tools with permission
checking and result handling.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ToolExecutionStatus(str, Enum):
    """Status of tool execution."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ToolExecutionRequest:
    """Request to execute a tool.

    Attributes:
        tool_name: Name of the tool to execute
        arguments: Arguments to pass to the tool
        tool_call_id: Unique identifier for this call
        project_id: Project context for execution
        user_id: User requesting execution
        session_id: Session context
        sandbox_id: Optional sandbox for execution
        timeout: Execution timeout in seconds
        metadata: Additional execution metadata
    """

    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str
    project_id: str
    user_id: str | None = None
    session_id: str | None = None
    sandbox_id: str | None = None
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolExecutionResult:
    """Result from tool execution.

    Attributes:
        tool_call_id: ID of the executed tool call
        tool_name: Name of the executed tool
        status: Execution status
        output: Tool output (string or structured)
        error: Error message if failed
        duration_ms: Execution duration in milliseconds
        artifacts: Generated artifacts (files, images, etc.)
        metadata: Additional result metadata
    """

    tool_call_id: str
    tool_name: str
    status: ToolExecutionStatus
    output: str = ""
    error: str | None = None
    duration_ms: float | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ToolExecutionStatus.SUCCESS

    def to_message_content(self) -> str:
        """Convert to content for LLM message."""
        if self.success:
            return self.output
        return f"Error: {self.error or 'Unknown error'}"


@runtime_checkable
class ToolExecutorPort(Protocol):
    """
    Protocol for tool execution.

    Implementations handle tool lookup, permission checking,
    and actual execution of tools.

    Example:
        class ToolExecutor(ToolExecutorPort):
            async def execute(
                self, request: ToolExecutionRequest
            ) -> ToolExecutionResult:
                tool = self._get_tool(request.tool_name)
                if not self._check_permission(tool, request):
                    return ToolExecutionResult(
                        status=ToolExecutionStatus.PERMISSION_DENIED,
                        ...
                    )
                result = await tool.execute(**request.arguments)
                return ToolExecutionResult(
                    status=ToolExecutionStatus.SUCCESS,
                    output=result.output,
                    ...
                )
    """

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """
        Execute a single tool.

        Args:
            request: Tool execution request

        Returns:
            Execution result with output or error
        """
        ...

    async def execute_batch(
        self, requests: list[ToolExecutionRequest]
    ) -> list[ToolExecutionResult]:
        """
        Execute multiple tools (potentially in parallel).

        Args:
            requests: List of tool execution requests

        Returns:
            List of execution results in same order as requests
        """
        ...

    async def execute_stream(
        self, request: ToolExecutionRequest
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute a tool with streaming output.

        Args:
            request: Tool execution request

        Yields:
            Stream events during execution

        Returns:
            Final execution result
        """
        ...

    def get_available_tools(self, project_id: str) -> list[dict[str, Any]]:
        """
        Get list of available tools for a project.

        Args:
            project_id: Project to get tools for

        Returns:
            List of tool definitions in OpenAI format
        """
        ...

    def has_tool(self, tool_name: str) -> bool:
        """
        Check if a tool exists.

        Args:
            tool_name: Name of tool to check

        Returns:
            True if tool exists
        """
        ...
