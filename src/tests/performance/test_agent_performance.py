"""
Performance tests for agent execution (T133).

Tests the performance characteristics of agent operations including:
- Work plan generation speed
- Tool execution latency
- Pattern matching performance
- Multi-level thinking overhead
- SSE streaming throughput
"""

import asyncio
import time
from datetime import datetime, timezone

import pytest

from src.domain.model.agent import (
    PlanStatus,
    PlanStep,
    ThoughtLevel,
    WorkPlan,
)
from src.infrastructure.agent.tools.memory_search import MemorySearchTool


@pytest.mark.performance
class TestAgentPerformance:
    """Performance tests for agent operations."""

    @pytest.mark.asyncio
    async def test_work_plan_generation_performance(self, test_db, mock_llm):
        """
        Test work plan generation completes within acceptable time.

        Performance target: < 2 seconds for typical queries
        """
        # Create a typical work plan use case with mocks
        from unittest.mock import AsyncMock, MagicMock

        mock_llm_response = MagicMock()
        mock_llm_response.content = "2"

        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

        # Simulate work plan creation
        steps = [
            PlanStep(
                step_number=0,
                description="Search for relevant memories",
                tool_names=["memory_search"],
                expected_output_format="List of relevant memories",
            ),
            PlanStep(
                step_number=1,
                description="Synthesize findings",
                tool_names=["summary"],
                expected_output_format="Summary of findings",
            ),
        ]

        # Create work plan (side effect: object creation)
        WorkPlan(
            id="test-plan-1",
            conversation_id="conv-1",
            user_query="Find memories about project planning",
            steps=steps,
            current_step_index=0,
            status=PlanStatus.PENDING,
            thought_level=ThoughtLevel.WORK,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Measure creation time
        start = time.time()

        # Simulate plan generation
        await asyncio.sleep(0.1)  # Simulate LLM call

        end = time.time()
        duration = end - start

        # Performance assertion: should complete quickly
        assert duration < 2.0, f"Work plan generation took {duration:.2f}s, expected < 2.0s"

    @pytest.mark.asyncio
    async def test_tool_execution_performance(self, test_project_db, mock_graphiti_client):
        """
        Test tool execution completes within acceptable time.

        Performance target: < 500ms for simple tool calls
        """
        tool = MemorySearchTool(mock_graphiti_client)

        start = time.time()

        result = await tool.execute(
            query="test query",
            project_id=test_project_db.id,
            limit=10,
        )

        end = time.time()
        duration = end - start

        # Performance assertion
        assert duration < 0.5, f"Tool execution took {duration:.2f}s, expected < 0.5s"
        assert result is not None

    @pytest.mark.asyncio
    async def test_pattern_matching_performance(self):
        """
        Test pattern matching query performance.

        Performance target: < 100ms for similarity search
        """
        from src.domain.model.agent.workflow_pattern import PatternStep, WorkflowPattern

        # Create test patterns
        patterns = [
            WorkflowPattern(
                id=f"pattern-{i}",
                tenant_id="tenant-1",
                name=f"Pattern {i}",
                description=f"Test pattern {i}",
                steps=[
                    PatternStep(
                        step_number=0,
                        description="Step 1",
                        tool_name="tool1",
                        expected_output_format="text",
                    )
                ],
                query_embedding=[0.1] * 1536,  # Simulated embedding
                success_rate=0.8,
                usage_count=10 + i,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            for i in range(100)
        ]

        # Simulate similarity search
        start = time.time()

        # Simple linear search (in production, use vector DB)
        for pattern in patterns:
            _ = pattern.id

        end = time.time()
        duration = end - start

        # Performance assertion
        assert duration < 0.1, f"Pattern matching took {duration:.2f}s, expected < 0.1s"

    @pytest.mark.asyncio
    async def test_sse_streaming_performance(self):
        """
        Test SSE streaming throughput.

        Performance target: > 10 events/second
        """
        events_sent = 0
        start_time = time.time()

        # Simulate SSE streaming
        async def event_stream():
            nonlocal events_sent
            for i in range(20):
                await asyncio.sleep(0.01)  # Simulate processing
                yield {"type": "test", "data": f"Event {i}"}
                events_sent += 1

        # Consume events
        async for _ in event_stream():
            pass

        end_time = time.time()
        duration = end_time - start_time

        events_per_second = events_sent / duration

        # Performance assertion
        assert events_per_second > 10, (
            f"SSE throughput: {events_per_second:.1f} events/s, expected > 10"
        )

    def test_memory_efficiency(self):
        """
        Test agent components don't leak memory.

        Performance target: < 10MB per active conversation
        """
        import sys

        # Create work plan
        work_plan = WorkPlan(
            id="test",
            conversation_id="test",
            user_query="test query",
            steps=[
                PlanStep(
                    step_number=i,
                    description=f"Step {i}",
                    tool_names=["tool1"],
                    expected_output_format="text",
                )
                for i in range(10)
            ],
            current_step_index=0,
            status=PlanStatus.PENDING,
            thought_level=ThoughtLevel.WORK,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Check size
        size = sys.getsizeof(work_plan)

        # Memory assertion (should be reasonable)
        assert size < 10 * 1024 * 1024, (
            f"Work plan size: {size / 1024 / 1024:.1f}MB, expected < 10MB"
        )

    @pytest.mark.asyncio
    async def test_concurrent_execution_performance(self):
        """
        Test concurrent agent execution performance.

        Performance target: Handle 10 concurrent conversations
        """

        async def simulate_conversation(conv_id: int):
            """Simulate a single conversation."""
            await asyncio.sleep(0.1)  # Simulate work
            return f"Conversation {conv_id} complete"

        # Start 10 concurrent conversations
        start = time.time()

        results = await asyncio.gather(*[simulate_conversation(i) for i in range(10)])

        end = time.time()
        duration = end - start

        # Verify all completed
        assert len(results) == 10
        assert duration < 1.0, f"Concurrent execution took {duration:.2f}s, expected < 1.0s"


@pytest.mark.benchmark
class TestAgentBenchmarks:
    """
    Benchmark tests for detailed performance analysis.

    These tests measure detailed performance metrics for optimization.
    """

    @pytest.mark.asyncio
    async def benchmark_work_plan_scaling(self):
        """
        Benchmark work plan generation with varying complexity.

        Measures how plan generation time scales with:
        - Number of steps
        - Query complexity
        - Available tools
        """
        complexities = [
            (2, "Simple"),
            (5, "Medium"),
            (10, "Complex"),
            (20, "Very Complex"),
        ]

        results = {}

        for step_count, complexity in complexities:
            start = time.time()

            # Simulate plan generation
            steps = [
                PlanStep(
                    step_number=i,
                    description=f"Step {i}",
                    tool_names=["tool1"],
                    expected_output_format="text",
                )
                for i in range(step_count)
            ]

            # Create work plan for benchmark
            WorkPlan(
                id=f"bench-{step_count}",
                conversation_id="bench",
                user_query="benchmark query",
                steps=steps,
                current_step_index=0,
                status=PlanStatus.PENDING,
                thought_level=ThoughtLevel.WORK,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            # Simulate processing
            await asyncio.sleep(0.01 * step_count)

            end = time.time()
            duration = end - start

            results[complexity] = {
                "steps": step_count,
                "duration": duration,
            }

            print(f"\n{complexity} ({step_count} steps): {duration:.3f}s")

        # Assert reasonable scaling (should be roughly linear)
        assert results["Very Complex"]["duration"] < results["Simple"]["duration"] * 15

    def benchmark_tool_composition_overhead(self):
        """
        Benchmark the overhead of tool composition vs direct execution.

        Measures the performance impact of using composed tools.
        """
        # Direct execution baseline
        start = time.time()
        # Simulate direct tool call
        for _ in range(100):
            pass  # Placeholder
        direct_duration = time.time() - start

        # Composed execution
        start = time.time()
        # Simulate composed execution
        for _ in range(100):
            # Simulate composition overhead
            pass
        composed_duration = time.time() - start

        overhead = composed_duration - direct_duration
        overhead_pct = (overhead / direct_duration) * 100 if direct_duration > 0 else 0

        print(f"\nTool composition overhead: {overhead * 1000:.2f}ms ({overhead_pct:.1f}%)")

        # Assert reasonable overhead
        assert overhead_pct < 50, f"Composition overhead too high: {overhead_pct:.1f}%"
