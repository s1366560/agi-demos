"""Tool Registry and Executor for ReActAgent.

Provides centralized tool management, execution, and monitoring.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

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
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
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
    parameters: Dict[str, Any]
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
    async def execute(self, **kwargs) -> Any:
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
        self._tools: Dict[str, Tool] = {}
        self._metadata: Dict[str, ToolMetadata] = {}
        self._status: Dict[str, ToolStatus] = {}
        self._execution_stats: Dict[str, Dict[str, Any]] = {}

    def register(self, tool: Tool, metadata: Optional[ToolMetadata] = None) -> None:
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
            "errors": 0,
            "total_duration_ms": 0,
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

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name.

        Args:
            name: The tool name

        Returns:
            The tool instance or None
        """
        return self._tools.get(name)

    def list_tools(
        self,
        category: Optional[str] = None,
        status: Optional[ToolStatus] = None,
    ) -> List[str]:
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

    def get_metadata(self, name: str) -> Optional[ToolMetadata]:
        """Get tool metadata.

        Args:
            name: The tool name

        Returns:
            Tool metadata or None
        """
        return self._metadata.get(name)

    def get_stats(self, name: str) -> Optional[Dict[str, Any]]:
        """Get execution statistics for a tool.

        Args:
            name: The tool name

        Returns:
            Statistics dictionary or None
        """
        return self._execution_stats.get(name)

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
        parameters: Dict[str, Any],
        timeout_seconds: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
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

        # Update stats
        stats = self._registry._execution_stats.get(tool_name)
        if stats:
            stats["calls"] += 1

        start_time = asyncio.get_event_loop().time()

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                tool.execute(**parameters),
                timeout=timeout,
            )

            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            # Update stats
            if stats:
                stats["total_duration_ms"] += duration_ms

            return ToolExecutionResult(
                tool_name=tool_name,
                success=True,
                result=result,
                duration_ms=duration_ms,
            )

        except asyncio.TimeoutError:
            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            if stats:
                stats["errors"] += 1

            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                result=None,
                error=f"Tool execution timed out after {timeout}s",
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            if stats:
                stats["errors"] += 1

            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                result=None,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def execute_batch(
        self,
        requests: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[ToolExecutionResult]:
        """Execute multiple tools in parallel.

        Args:
            requests: List of tool execution requests
            context: Optional execution context

        Returns:
            List of execution results
        """
        tasks = [
            self.execute(
                tool_name=req.get("tool_name"),
                parameters=req.get("parameters", {}),
                timeout_seconds=req.get("timeout_seconds"),
                context=context,
            )
            for req in requests
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions in gather
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                requests[i]  # type: ignore
                results[i] = ToolExecutionResult(
                    tool_name=requests[i].get("tool_name", "unknown"),
                    success=False,
                    result=None,
                    error=str(result),
                )

        return results


# Global tool registry
_global_registry: Optional[ToolRegistry] = None


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
