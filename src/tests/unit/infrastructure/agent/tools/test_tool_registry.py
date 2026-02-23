"""Tests for Tool Registry and Executor.

Tests the centralized tool management system.
"""

import asyncio
from typing import Any

import pytest

from src.infrastructure.agent.tools.tool_registry import (
    Tool,
    ToolExecutionResult,
    ToolExecutor,
    ToolMetadata,
    ToolRegistry,
    ToolStatus,
    get_tool_executor,
    get_tool_registry,
    set_tool_registry,
)


class MockTool(Tool):
    """Mock tool for testing."""

    def __init__(
        self,
        name: str = "test_tool",
        description: str = "A test tool",
        execute_result: Any = "success",
        should_fail: bool = False,
        delay_ms: float = 0,
        category: str = "test",
    ) -> None:
        """Initialize mock tool."""
        self._name = name
        self._description = description
        self._execute_result = execute_result
        self._should_fail = should_fail
        self._delay_ms = delay_ms
        self._category = category

    @property
    def name(self) -> str:
        """Tool name."""
        return self._name

    @property
    def description(self) -> str:
        """Tool description."""
        return self._description

    async def execute(self, **kwargs) -> Any:
        """Execute the tool."""
        if self._delay_ms:
            await asyncio.sleep(self._delay_ms / 1000)

        if self._should_fail:
            raise ValueError("Tool execution failed")

        return self._execute_result

    def get_metadata(self) -> ToolMetadata:
        """Get tool metadata."""
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category=self._category,
            parameters={},
            requires_permission=True,
            dangerous=False,
            safe=False,
        )


class SlowMockTool(Tool):
    """Mock tool that takes time to execute."""

    def __init__(self, delay: float = 1.0):
        """Initialize slow tool."""
        self._delay = delay
        self._name = "slow_tool"
        self._description = "A slow tool"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, **kwargs) -> Any:
        await asyncio.sleep(self._delay)
        return "slow_result"


class TestToolStatus:
    """Tests for ToolStatus enum."""

    def test_status_values(self) -> None:
        """Should have correct status values."""
        assert ToolStatus.REGISTERED.value == "registered"
        assert ToolStatus.ACTIVE.value == "active"
        assert ToolStatus.DISABLED.value == "disabled"
        assert ToolStatus.ERROR.value == "error"


class TestToolExecutionResult:
    """Tests for ToolExecutionResult."""

    def test_create_successful_result(self) -> None:
        """Should create successful result."""
        result = ToolExecutionResult(
            tool_name="test_tool",
            success=True,
            result="output",
        )

        assert result.tool_name == "test_tool"
        assert result.success is True
        assert result.result == "output"
        assert result.error is None

    def test_create_failed_result(self) -> None:
        """Should create failed result."""
        result = ToolExecutionResult(
            tool_name="test_tool",
            success=False,
            result=None,
            error="Execution failed",
        )

        assert result.success is False
        assert result.error == "Execution failed"

    def test_to_dict(self) -> None:
        """Should convert to dictionary."""
        result = ToolExecutionResult(
            tool_name="test_tool",
            success=True,
            result={"key": "value"},
        )

        data = result.to_dict()

        assert data["tool_name"] == "test_tool"
        assert data["success"] is True
        assert data["result"] == {"key": "value"}
        assert "timestamp" in data


class TestToolMetadata:
    """Tests for ToolMetadata."""

    def test_create_metadata(self) -> None:
        """Should create metadata with defaults."""
        metadata = ToolMetadata(
            name="test_tool",
            description="A test tool",
            category="test",
            parameters={"param1": "string"},
        )

        assert metadata.name == "test_tool"
        assert metadata.category == "test"
        assert metadata.requires_permission is True
        assert metadata.dangerous is False

    def test_safe_tool_metadata(self) -> None:
        """Should mark safe tools appropriately."""
        metadata = ToolMetadata(
            name="safe_tool",
            description="A safe tool",
            category="test",
            parameters={},
            safe=True,
        )

        assert metadata.safe is True


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_register_tool(self) -> None:
        """Should register a tool."""
        registry = ToolRegistry()
        tool = MockTool()

        registry.register(tool)

        assert registry.get_tool("test_tool") is tool
        assert "test_tool" in registry.list_tools()

    def test_register_duplicate_raises_error(self) -> None:
        """Should raise error when registering duplicate."""
        registry = ToolRegistry()
        tool = MockTool()

        registry.register(tool)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(tool)

    def test_unregister_tool(self) -> None:
        """Should unregister a tool."""
        registry = ToolRegistry()
        tool = MockTool()

        registry.register(tool)
        assert "test_tool" in registry.list_tools()

        registry.unregister("test_tool")

        assert registry.get_tool("test_tool") is None
        assert "test_tool" not in registry.list_tools()

    def test_list_tools_by_category(self) -> None:
        """Should filter tools by category."""
        registry = ToolRegistry()
        registry.register(MockTool("tool1", category="cat1"))
        registry.register(MockTool("tool2", category="cat2"))
        registry.register(MockTool("tool3", category="cat1"))

        cat1_tools = registry.list_tools(category="cat1")
        all_tools = registry.list_tools()

        assert len(cat1_tools) == 2
        assert len(all_tools) == 3

    def test_list_tools_by_status(self) -> None:
        """Should filter tools by status."""
        registry = ToolRegistry()
        tool = MockTool()
        registry.register(tool)

        active_tools = registry.list_tools(status=ToolStatus.REGISTERED)
        disabled_tools = registry.list_tools(status=ToolStatus.DISABLED)

        assert len(active_tools) == 1
        assert len(disabled_tools) == 0

    def test_get_metadata(self) -> None:
        """Should get tool metadata."""
        registry = ToolRegistry()
        tool = MockTool(
            description="Custom description",
            category="custom",
        )

        registry.register(tool)

        metadata = registry.get_metadata("test_tool")
        assert metadata.description == "Custom description"
        assert metadata.category == "custom"

    def test_get_stats(self) -> None:
        """Should track execution statistics."""
        registry = ToolRegistry()
        tool = MockTool()
        registry.register(tool)

        stats = registry.get_stats("test_tool")
        assert stats is not None
        assert stats["calls"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["avg_duration_ms"] == 0.0

    def test_record_execution_updates_derived_metrics(self) -> None:
        """Derived quality metrics should update on each record_execution call."""
        registry = ToolRegistry()
        registry.register(MockTool())

        registry.record_execution("test_tool", success=True, duration_ms=100.0)
        registry.record_execution("test_tool", success=False, duration_ms=400.0)

        stats = registry.get_stats("test_tool")
        assert stats is not None
        assert stats["calls"] == 2
        assert stats["successes"] == 1
        assert stats["errors"] == 1
        assert stats["total_duration_ms"] == 500.0
        assert stats["avg_duration_ms"] == 250.0
        assert stats["success_rate"] == 0.5

    def test_get_quality_scores_combines_success_and_latency(self) -> None:
        """Quality score should reward reliable and fast tools."""
        registry = ToolRegistry()
        registry.register(MockTool("fast_tool"))
        registry.register(MockTool("slow_tool"))

        for _ in range(3):
            registry.record_execution("fast_tool", success=True, duration_ms=120.0)
        for _ in range(3):
            registry.record_execution("slow_tool", success=False, duration_ms=3500.0)

        quality = registry.get_quality_scores()
        assert quality["fast_tool"] > quality["slow_tool"]
        assert 0.0 <= quality["fast_tool"] <= 1.0

    def test_enable_disable_tool(self) -> None:
        """Should enable and disable tools."""
        registry = ToolRegistry()
        tool = MockTool()
        registry.register(tool)

        # Disable
        registry.disable_tool("test_tool")
        disabled = registry.list_tools(status=ToolStatus.DISABLED)
        assert len(disabled) == 1

        # Enable
        registry.enable_tool("test_tool")
        enabled = registry.list_tools(status=ToolStatus.ACTIVE)
        assert len(enabled) == 1


class TestToolExecutor:
    """Tests for ToolExecutor."""

    @pytest.mark.asyncio
    async def test_execute_successful_tool(self) -> None:
        """Should execute tool successfully."""
        registry = ToolRegistry()
        tool = MockTool(execute_result="result_value")
        registry.register(tool)

        executor = ToolExecutor(registry)

        result = await executor.execute("test_tool", {})

        assert result.success is True
        assert result.result == "result_value"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self) -> None:
        """Should handle nonexistent tool gracefully."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        result = await executor.execute("nonexistent", {})

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_tool_with_timeout(self) -> None:
        """Should timeout slow tools."""
        registry = ToolRegistry()
        tool = SlowMockTool(delay=10.0)
        registry.register(tool)

        executor = ToolExecutor(registry, default_timeout_seconds=0.5)

        result = await executor.execute("slow_tool", {})

        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_updates_stats(self) -> None:
        """Should update execution statistics."""
        registry = ToolRegistry()
        tool = MockTool(execute_result="ok")
        registry.register(tool)

        executor = ToolExecutor(registry)

        # Successful execution
        await executor.execute("test_tool", {})

        stats = registry.get_stats("test_tool")
        assert stats["calls"] == 1
        assert stats["errors"] == 0
        assert stats["total_duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_execute_batch(self) -> None:
        """Should execute multiple tools in parallel."""
        registry = ToolRegistry()
        tool1 = MockTool("tool1", execute_result="result1")
        tool2 = MockTool("tool2", execute_result="result2")
        tool3 = MockTool("tool3", execute_result="result3")

        registry.register(tool1)
        registry.register(tool2)
        registry.register(tool3)

        executor = ToolExecutor(registry)

        requests = [
            {"tool_name": "tool1", "parameters": {}},
            {"tool_name": "tool2", "parameters": {}},
            {"tool_name": "tool3", "parameters": {}},
        ]

        results = await executor.execute_batch(requests)

        assert len(results) == 3
        assert all(r.success for r in results)
        assert results[0].result == "result1"
        assert results[1].result == "result2"
        assert results[2].result == "result3"

    @pytest.mark.asyncio
    async def test_execute_batch_with_failures(self) -> None:
        """Should handle failures in batch execution."""
        registry = ToolRegistry()
        tool1 = MockTool("tool1", execute_result="result1")
        tool2 = MockTool("tool2", should_fail=True)

        registry.register(tool1)
        registry.register(tool2)

        executor = ToolExecutor(registry)

        requests = [
            {"tool_name": "tool1", "parameters": {}},
            {"tool_name": "tool2", "parameters": {}},
        ]

        results = await executor.execute_batch(requests)

        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False


class TestGlobalToolRegistry:
    """Tests for global tool registry singleton."""

    def test_get_tool_registry_returns_singleton(self) -> None:
        """Should return same instance across calls."""
        registry1 = get_tool_registry()
        registry2 = get_tool_registry()

        assert registry1 is registry2

    def test_set_tool_registry_changes_global(self) -> None:
        """Should allow changing global registry."""
        original = get_tool_registry()
        custom = ToolRegistry()

        set_tool_registry(custom)

        assert get_tool_registry() is custom
        assert get_tool_registry() is not original

    def test_get_tool_executor(self) -> None:
        """Should create executor with global registry."""
        executor = get_tool_executor()

        assert isinstance(executor, ToolExecutor)
        assert executor._registry is get_tool_registry()
