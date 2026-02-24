"""Tool Registry and Executor for ReActAgent.

Provides centralized tool management, execution, and monitoring.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ToolStatus(Enum):
    """Status of a tool in the registry."""

    REGISTERED = "registered"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class ToolExecutionResult:
    """Result of a tool execution."""

    tool_name: str
    success: bool
    result: Any
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class ToolMetadata:
    """Metadata for a registered tool."""

    name: str
    description: str
    category: str
    parameters: dict[str, Any]
    requires_permission: bool = True
    dangerous: bool = False
    safe: bool = False
    timeout_seconds: float = 30.0
    scope: str = "tenant"  # system, tenant, project


class Tool(ABC):
    """Abstract base class for agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            Execution result
        """
        ...

    def get_metadata(self) -> ToolMetadata:
        """Get tool metadata."""
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category="general",
            parameters={},
            requires_permission=True,
            dangerous=False,
            safe=False,
        )


class ToolRegistry:
    """
    Central registry for agent tools.

    Manages tool registration, discovery, and lifecycle.
    """

    def __init__(self) -> None:
        """Initialize the tool registry."""
        self._tools: dict[str, Tool] = {}
        self._metadata: dict[str, ToolMetadata] = {}
        self._status: dict[str, ToolStatus] = {}
        self._execution_stats: dict[str, dict[str, Any]] = {}

    def register(self, tool: Tool, metadata: ToolMetadata | None = None) -> None:
        """Register a tool.

        Args:
            tool: The tool instance to register
            metadata: Optional custom metadata

        Raises:
            ValueError: If tool name already registered
        """
        name = tool.name

        if name in self._tools:
            raise ValueError(f"Tool '{name}' already registered")

        self._tools[name] = tool
        self._metadata[name] = metadata or tool.get_metadata()
        self._status[name] = ToolStatus.REGISTERED
        self._execution_stats[name] = {
            "calls": 0,
            "successes": 0,
            "errors": 0,
            "total_duration_ms": 0.0,
            "avg_duration_ms": 0.0,
            "success_rate": 0.0,
        }

        logger.info(f"Registered tool: {name}")

    def unregister(self, name: str) -> None:
        """Unregister a tool.

        Args:
            name: The tool name to unregister
        """
        if name in self._tools:
            del self._tools[name]
            del self._metadata[name]
            del self._status[name]
            logger.info(f"Unregistered tool: {name}")

    def get_tool(self, name: str) -> Tool | None:
        """Get a tool by name.

        Args:
            name: The tool name

        Returns:
            The tool instance or None
        """
        return self._tools.get(name)

    def list_tools(
        self,
        category: str | None = None,
        status: ToolStatus | None = None,
    ) -> list[str]:
        """List registered tools.

        Args:
            category: Optional category filter
            status: Optional status filter

        Returns:
            List of tool names
        """
        tools = []

        for name, metadata in self._metadata.items():
            if category and metadata.category != category:
                continue
            if status and self._status.get(name) != status:
                continue
            tools.append(name)

        return sorted(tools)

    def get_metadata(self, name: str) -> ToolMetadata | None:
        """Get tool metadata.

        Args:
            name: The tool name

        Returns:
            Tool metadata or None
        """
        return self._metadata.get(name)

    def get_stats(self, name: str) -> dict[str, Any] | None:
        """Get execution statistics for a tool.

        Args:
            name: The tool name

        Returns:
            Statistics dictionary or None
        """
        return self._execution_stats.get(name)

    def record_execution(self, name: str, *, success: bool, duration_ms: float) -> None:
        """Record one tool execution and refresh derived quality metrics."""
        stats = self._execution_stats.get(name)
        if stats is None:
            return

        stats["calls"] = int(stats.get("calls", 0)) + 1
        if success:
            stats["successes"] = int(stats.get("successes", 0)) + 1
        else:
            stats["errors"] = int(stats.get("errors", 0)) + 1
        stats["total_duration_ms"] = float(stats.get("total_duration_ms", 0.0)) + max(
            0.0, float(duration_ms)
        )

        calls = int(stats.get("calls", 0))
        successes = int(stats.get("successes", 0))
        total_duration = float(stats.get("total_duration_ms", 0.0))
        stats["avg_duration_ms"] = total_duration / calls if calls else 0.0
        stats["success_rate"] = successes / calls if calls else 0.0

    def get_quality_scores(self) -> dict[str, float]:
        """Return normalized quality scores (0.0-1.0) for ranking feedback."""
        quality_scores: dict[str, float] = {}
        for name, stats in self._execution_stats.items():
            calls = int(stats.get("calls", 0))
            if calls <= 0:
                quality_scores[name] = 0.5
                continue

            success_rate = float(stats.get("success_rate", 0.0))
            avg_duration_ms = float(stats.get("avg_duration_ms", 0.0))
            latency_penalty = min(max(avg_duration_ms, 0.0) / 5000.0, 1.0) * 0.2
            score = max(0.0, min(1.0, success_rate - latency_penalty))
            quality_scores[name] = round(score, 4)
        return quality_scores

    def enable_tool(self, name: str) -> None:
        """Enable a tool.

        Args:
            name: The tool name
        """
        if name in self._status:
            self._status[name] = ToolStatus.ACTIVE

    def disable_tool(self, name: str) -> None:
        """Disable a tool.

        Args:
            name: The tool name
        """
        if name in self._status:
            self._status[name] = ToolStatus.DISABLED


class ToolExecutor:
    """
    Executes tools with monitoring and error handling.

    Provides unified tool execution interface with timeout,
    retry, and result normalization.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        default_timeout_seconds: float = 30.0,
        max_retries: int = 1,
    ) -> None:
        """Initialize the tool executor.

        Args:
            registry: Tool registry to use
            default_timeout_seconds: Default timeout for tool execution
            max_retries: Maximum retry attempts for transient failures
        """
        self._registry = registry
        self._default_timeout = default_timeout_seconds
        self._max_retries = max_retries

    async def execute(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        timeout_seconds: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        """Execute a tool with monitoring.

        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters
            timeout_seconds: Override default timeout
            context: Optional execution context

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool not found
            TimeoutError: If tool execution times out
        """
        tool = self._registry.get_tool(tool_name)

        if tool is None:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                result=None,
                error=f"Tool '{tool_name}' not found",
            )

        timeout = timeout_seconds or self._default_timeout

        start_time = asyncio.get_event_loop().time()

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                tool.execute(**parameters),
                timeout=timeout,
            )

            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            self._registry.record_execution(
                tool_name,
                success=True,
                duration_ms=duration_ms,
            )

            return ToolExecutionResult(
                tool_name=tool_name,
                success=True,
                result=result,
                duration_ms=duration_ms,
            )

        except TimeoutError:
            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            self._registry.record_execution(
                tool_name,
                success=False,
                duration_ms=duration_ms,
            )

            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                result=None,
                error=f"Tool execution timed out after {timeout}s",
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            self._registry.record_execution(
                tool_name,
                success=False,
                duration_ms=duration_ms,
            )

            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                result=None,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def execute_batch(
        self,
        requests: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> list[ToolExecutionResult]:
        """Execute multiple tools in parallel.

        Args:
            requests: List of tool execution requests
            context: Optional execution context

        Returns:
            List of execution results
        """
        normalized_requests: list[dict[str, Any]] = []
        for req in requests:
            raw_tool_name = req.get("tool_name")
            tool_name = raw_tool_name.strip() if isinstance(raw_tool_name, str) else ""
            parameters = req.get("parameters")
            normalized_requests.append(
                {
                    "tool_name": tool_name or "unknown",
                    "parameters": parameters if isinstance(parameters, dict) else {},
                    "timeout_seconds": req.get("timeout_seconds"),
                }
            )

        tasks = [
            self.execute(
                tool_name=req["tool_name"],
                parameters=req["parameters"],
                timeout_seconds=req.get("timeout_seconds"),
                context=context,
            )
            for req in normalized_requests
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions in gather
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                results[i] = ToolExecutionResult(
                    tool_name=normalized_requests[i].get("tool_name", "unknown"),
                    success=False,
                    result=None,
                    error=str(result),
                )

        return results


# Global tool registry
_global_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry.

    Returns:
        The global ToolRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def set_tool_registry(registry: ToolRegistry) -> None:
    """Set the global tool registry.

    Args:
        registry: The tool registry to use globally
    """
    global _global_registry
    _global_registry = registry


def get_tool_executor() -> ToolExecutor:
    """Get the global tool executor.

    Returns:
        A ToolExecutor using the global registry
    """
    return ToolExecutor(get_tool_registry())
