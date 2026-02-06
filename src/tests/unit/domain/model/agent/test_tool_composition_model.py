"""
Unit tests for ToolComposition entity (T104)

Tests the ToolComposition domain entity which represents
composed tool chains for complex task execution.

TDD: Tests written first, entity will be implemented to make these pass.
"""

from datetime import datetime

import pytest

from src.domain.model.agent.tool_composition import ToolComposition


class TestToolComposition:
    """Tests for ToolComposition entity."""

    def test_tool_composition_creation(self):
        """Test creating a valid tool composition."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Search and Summarize",
            description="Search memories and summarize results",
            tools=["memory_search", "summary"],
            execution_template={"type": "sequential"},
        )

        assert composition.id == "comp-123"
        assert composition.name == "Search and Summarize"
        assert composition.description == "Search memories and summarize results"
        assert composition.tools == ["memory_search", "summary"]
        assert composition.execution_template == {"type": "sequential"}

    def test_tool_composition_with_defaults(self):
        """Test creating composition with default values."""
        composition = ToolComposition(
            id="comp-456",
            tenant_id="test-tenant",
            name="Simple Composition",
            description="A simple composition",
            tools=["search"],
        )

        assert composition.execution_template == {}
        assert composition.success_count == 0
        assert composition.failure_count == 0
        assert composition.usage_count == 0
        assert isinstance(composition.created_at, datetime)
        assert isinstance(composition.updated_at, datetime)

    def test_tool_composition_validation_empty_name(self):
        """Test that empty name raises validation error."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            ToolComposition(
                id="comp-123",
                tenant_id="test-tenant",
            name="",
                description="Description",
                tools=["tool1"],
            )

    def test_tool_composition_validation_empty_tools(self):
        """Test that empty tools list raises validation error."""
        with pytest.raises(ValueError, match="tools cannot be empty"):
            ToolComposition(
                id="comp-123",
                tenant_id="test-tenant",
            name="Composition",
                description="Description",
                tools=[],
            )

    def test_tool_composition_validation_negative_counts(self):
        """Test that negative counts raise validation errors."""
        # Negative success_count
        with pytest.raises(ValueError, match="success_count must be non-negative"):
            ToolComposition(
                id="comp-123",
                tenant_id="test-tenant",
            name="Composition",
                description="Description",
                tools=["tool1"],
                success_count=-1,
            )

        # Negative failure_count
        with pytest.raises(ValueError, match="failure_count must be non-negative"):
            ToolComposition(
                id="comp-123",
                tenant_id="test-tenant",
            name="Composition",
                description="Description",
                tools=["tool1"],
                failure_count=-1,
            )

        # Negative usage_count
        with pytest.raises(ValueError, match="usage_count must be non-negative"):
            ToolComposition(
                id="comp-123",
                tenant_id="test-tenant",
            name="Composition",
                description="Description",
                tools=["tool1"],
                usage_count=-1,
            )

    def test_success_rate_calculation(self):
        """Test success rate property calculation."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test Composition",
            description="Test",
            tools=["tool1", "tool2"],
            success_count=7,
            failure_count=3,
        )

        assert composition.success_rate == 0.7

    def test_success_rate_no_executions(self):
        """Test success rate when never executed defaults to 1.0."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test Composition",
            description="Test",
            tools=["tool1"],
            success_count=0,
            failure_count=0,
        )

        assert composition.success_rate == 1.0

    def test_get_primary_tool(self):
        """Test getting the primary tool from composition."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Multi Tool",
            description="Test",
            tools=["search", "summarize", "format"],
        )

        assert composition.get_primary_tool() == "search"

    def test_get_primary_tool_empty_invalid(self):
        """Test that composition with empty tools is invalid."""
        with pytest.raises(ValueError, match="tools cannot be empty"):
            ToolComposition(
                id="comp-123",
                tenant_id="test-tenant",
            name="Empty",
                description="Test",
                tools=[],
            )

    def test_can_execute_with_all_available(self):
        """Test checking if composition can execute with all tools available."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test",
            tools=["search", "summarize"],
        )

        available = {"search", "summarize", "format"}
        assert composition.can_execute_with(available) is True

    def test_can_execute_with_missing_tools(self):
        """Test checking if composition can execute with missing tools."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test",
            tools=["search", "summarize"],
        )

        available = {"search", "format"}
        assert composition.can_execute_with(available) is False

    def test_has_circular_dependency_none(self):
        """Test circular dependency check with unique tools."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Linear",
            description="Test",
            tools=["tool1", "tool2", "tool3"],
        )

        assert composition.has_circular_dependency() is False

    def test_has_circular_dependency_duplicate(self):
        """Test circular dependency check with duplicate tools."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Circular",
            description="Test",
            tools=["tool1", "tool2", "tool1"],
        )

        assert composition.has_circular_dependency() is True

    def test_record_usage_success(self):
        """Test recording successful usage."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test",
            tools=["tool1"],
            success_count=5,
            failure_count=2,
            usage_count=7,
        )

        updated = composition.record_usage(success=True)

        assert updated.success_count == 6
        assert updated.failure_count == 2
        assert updated.usage_count == 8
        assert updated.id == composition.id
        assert updated.name == composition.name

    def test_record_usage_failure(self):
        """Test recording failed usage."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test",
            tools=["tool1"],
            success_count=5,
            failure_count=2,
            usage_count=7,
        )

        updated = composition.record_usage(success=False)

        assert updated.success_count == 5
        assert updated.failure_count == 3
        assert updated.usage_count == 8

    def test_get_fallback_tools(self):
        """Test getting fallback tools from template."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test",
            tools=["tool1"],
            execution_template={
                "type": "sequential",
                "fallback_alternatives": ["tool2", "tool3"],
            },
        )

        fallback = composition.get_fallback_tools()
        assert fallback == ["tool2", "tool3"]

    def test_get_fallback_tools_empty(self):
        """Test getting fallback tools when none defined."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test",
            tools=["tool1"],
            execution_template={},
        )

        fallback = composition.get_fallback_tools()
        assert fallback == []

    def test_get_composition_type(self):
        """Test getting composition type from template."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test",
            tools=["tool1"],
            execution_template={"type": "parallel", "aggregation": "merge"},
        )

        assert composition.get_composition_type() == "parallel"

    def test_get_composition_type_default(self):
        """Test getting composition type defaults to sequential."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test",
            tools=["tool1"],
            execution_template={},
        )

        assert composition.get_composition_type() == "sequential"

    def test_to_dict(self):
        """Test converting composition to dictionary."""
        composition = ToolComposition(
            id="comp-123",
            tenant_id="test-tenant",
            name="Test",
            description="Test description",
            tools=["tool1", "tool2"],
            execution_template={"type": "sequential"},
            success_count=8,
            failure_count=2,
            usage_count=10,
        )

        data = composition.to_dict()

        assert data["id"] == "comp-123"
        assert data["name"] == "Test"
        assert data["description"] == "Test description"
        assert data["tools"] == ["tool1", "tool2"]
        assert data["success_rate"] == 0.8
        assert data["success_count"] == 8
        assert data["failure_count"] == 2
        assert data["usage_count"] == 10
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_factory_method(self):
        """Test creating composition using factory method."""
        composition = ToolComposition.create(
            tenant_id="test-tenant",
            name="Search and Summarize",
            description="Search memories and summarize",
            tools=["memory_search", "summary"],
            composition_type="sequential",
            fallback_alternatives=["web_search"],
        )

        assert composition.name == "Search and Summarize"
        assert composition.description == "Search memories and summarize"
        assert composition.tools == ["memory_search", "summary"]
        assert composition.execution_template["type"] == "sequential"
        assert composition.execution_template["fallback_alternatives"] == ["web_search"]
        assert isinstance(composition.id, str)
        assert len(composition.id) > 0

    def test_from_dict(self):
        """Test creating composition from dictionary."""
        data = {
            "id": "comp-123",
            "tenant_id": "test-tenant",
            "name": "Test",
            "description": "Test description",
            "tools": ["tool1", "tool2"],
            "execution_template": {"type": "parallel"},
            "success_count": 5,
            "failure_count": 1,
            "usage_count": 6,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T01:00:00Z",
        }

        composition = ToolComposition.from_dict(data)

        assert composition.id == "comp-123"
        assert composition.name == "Test"
        assert composition.tools == ["tool1", "tool2"]
        assert composition.execution_template["type"] == "parallel"
        assert composition.success_count == 5
        assert composition.failure_count == 1
        assert composition.usage_count == 6

    def test_from_dict_with_defaults(self):
        """Test creating composition from dictionary with missing fields."""
        data = {
            "id": "comp-123",
            "tenant_id": "test-tenant",
            "name": "Test",
            "description": "Test",
            "tools": ["tool1"],
        }

        composition = ToolComposition.from_dict(data)

        assert composition.execution_template == {}
        assert composition.success_count == 0
        assert composition.failure_count == 0
        assert composition.usage_count == 0
