"""
Unit tests for WorkflowPattern entity (T065)

Tests the WorkflowPattern domain entity which represents
learned workflow patterns from successful agent executions.

TDD: Tests written first, entity will be implemented to make these pass.
"""

from datetime import datetime, timezone

from src.domain.model.agent.workflow_pattern import PatternStep, WorkflowPattern


class TestPatternStep:
    """Tests for PatternStep value object."""

    def test_pattern_step_creation(self):
        """Test creating a valid pattern step."""
        step = PatternStep(
            step_number=1,
            description="Search for financial data",
            tool_name="memory_search",
            expected_output_format="structured",
            similarity_threshold=0.8,
        )

        assert step.step_number == 1
        assert step.description == "Search for financial data"
        assert step.tool_name == "memory_search"
        assert step.expected_output_format == "structured"
        assert step.similarity_threshold == 0.8

    def test_pattern_step_with_optional_fields(self):
        """Test pattern step with optional parameters."""
        step = PatternStep(
            step_number=2,
            description="Analyze trends",
            tool_name="trend_analysis",
            expected_output_format="chart",
            tool_parameters={"timeframe": "30d", "metrics": ["volume", "price"]},
            similarity_threshold=0.7,
        )

        assert step.tool_parameters == {"timeframe": "30d", "metrics": ["volume", "price"]}
        assert step.similarity_threshold == 0.7

    def test_pattern_step_equality(self):
        """Test that pattern steps with same values are equal."""
        step1 = PatternStep(
            step_number=1,
            description="Search",
            tool_name="search",
            expected_output_format="text",
            similarity_threshold=0.8,
        )
        step2 = PatternStep(
            step_number=1,
            description="Search",
            tool_name="search",
            expected_output_format="text",
            similarity_threshold=0.8,
        )

        assert step1 == step2

    def test_pattern_step_inequality(self):
        """Test that pattern steps with different values are not equal."""
        step1 = PatternStep(
            step_number=1,
            description="Search",
            tool_name="search",
            expected_output_format="text",
            similarity_threshold=0.8,
        )
        step2 = PatternStep(
            step_number=2,
            description="Analyze",
            tool_name="analyze",
            expected_output_format="text",
            similarity_threshold=0.8,
        )

        assert step1 != step2


class TestWorkflowPattern:
    """Tests for WorkflowPattern entity."""

    def test_workflow_pattern_creation(self):
        """Test creating a valid workflow pattern."""
        now = datetime.now(timezone.utc)
        steps = [
            PatternStep(
                step_number=1,
                description="Search for data",
                tool_name="memory_search",
                expected_output_format="structured",
                similarity_threshold=0.8,
            ),
            PatternStep(
                step_number=2,
                description="Analyze results",
                tool_name="analyze",
                expected_output_format="report",
                similarity_threshold=0.7,
            ),
        ]

        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Financial Analysis Pattern",
            description="Pattern for analyzing financial data",
            steps=steps,
            success_rate=0.95,
            usage_count=10,
            created_at=now,
            updated_at=now,
        )

        assert pattern.id == "pattern-1"
        assert pattern.tenant_id == "tenant-1"
        assert pattern.name == "Financial Analysis Pattern"
        assert len(pattern.steps) == 2
        assert pattern.success_rate == 0.95
        assert pattern.usage_count == 10

    def test_workflow_pattern_with_metadata(self):
        """Test workflow pattern with optional metadata."""
        now = datetime.now(timezone.utc)
        steps = [
            PatternStep(
                step_number=1,
                description="Search",
                tool_name="search",
                expected_output_format="text",
                similarity_threshold=0.8,
            )
        ]

        pattern = WorkflowPattern(
            id="pattern-2",
            tenant_id="tenant-1",
            name="Search Pattern",
            description="Basic search pattern",
            steps=steps,
            success_rate=0.9,
            usage_count=5,
            created_at=now,
            updated_at=now,
            metadata={"category": "search", "avg_duration_ms": 1500},
        )

        assert pattern.metadata == {"category": "search", "avg_duration_ms": 1500}

    def test_workflow_pattern_tenant_scoping(self):
        """Test that workflow patterns are tenant-scoped."""
        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Test Pattern",
            description="Test",
            steps=[],
            success_rate=1.0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Pattern should be scoped to tenant
        assert pattern.tenant_id == "tenant-1"

    def test_workflow_pattern_step_ordering(self):
        """Test that pattern steps maintain their order."""
        steps = [
            PatternStep(
                step_number=3,
                description="Third step",
                tool_name="tool3",
                expected_output_format="text",
                similarity_threshold=0.8,
            ),
            PatternStep(
                step_number=1,
                description="First step",
                tool_name="tool1",
                expected_output_format="text",
                similarity_threshold=0.8,
            ),
            PatternStep(
                step_number=2,
                description="Second step",
                tool_name="tool2",
                expected_output_format="text",
                similarity_threshold=0.8,
            ),
        ]

        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Test",
            description="Test",
            steps=steps,
            success_rate=1.0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Steps should be in the order provided (not sorted by step_number)
        assert pattern.steps[0].step_number == 3
        assert pattern.steps[1].step_number == 1
        assert pattern.steps[2].step_number == 2

    def test_workflow_pattern_similarity_calculation(self):
        """Test calculating similarity between patterns."""
        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Search Pattern",
            description="Pattern for searching memories",
            steps=[
                PatternStep(
                    step_number=1,
                    description="Search memories",
                    tool_name="memory_search",
                    expected_output_format="structured",
                    similarity_threshold=0.8,
                )
            ],
            success_rate=0.9,
            usage_count=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Similar pattern should have high similarity score
        query_description = "I need to search through stored memories"
        similarity = pattern.calculate_similarity(query_description)

        assert similarity > 0.5

    def test_workflow_pattern_low_similarity(self):
        """Test that dissimilar queries have low similarity."""
        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Chart Generation Pattern",
            description="Pattern for generating charts",
            steps=[
                PatternStep(
                    step_number=1,
                    description="Generate chart",
                    tool_name="chart_gen",
                    expected_output_format="chart",
                    similarity_threshold=0.8,
                )
            ],
            success_rate=0.9,
            usage_count=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Dissimilar query should have low similarity score
        query_description = "Send an email to the team"
        similarity = pattern.calculate_similarity(query_description)

        assert similarity < 0.5

    def test_workflow_pattern_update_success_rate(self):
        """Test updating pattern success rate based on execution result."""
        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Test Pattern",
            description="Test",
            steps=[],
            success_rate=0.8,
            usage_count=10,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Update with successful execution
        updated = pattern.update_execution_result(success=True)
        assert updated.success_rate > 0.8
        assert updated.usage_count == 11

        # Update with failed execution
        updated2 = updated.update_execution_result(success=False)
        assert updated2.success_rate < updated.success_rate
        assert updated2.usage_count == 12
