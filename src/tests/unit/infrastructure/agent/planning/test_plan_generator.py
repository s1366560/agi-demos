"""
Unit tests for PlanGenerator.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionPlanStatus,
    ExecutionStepStatus,
)
from src.infrastructure.agent.planning.plan_generator import PlanGenerator


def create_mock_llm(response: str) -> AsyncMock:
    """Helper to create an LLM mock that returns a specific response."""
    mock_llm = AsyncMock()
    # Mock the generate method to return the response
    mock_llm.generate = AsyncMock(return_value=response)
    return mock_llm


class TestPlanGeneratorInit:
    """Tests for PlanGenerator initialization."""

    def test_init_with_llm_client(self) -> None:
        """Test creating PlanGenerator with LLM client."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock()
        mock_tools = [
            Mock(name="MemorySearch", spec=["name", "description"]),
            Mock(name="EntityLookup", spec=["name", "description"]),
        ]

        generator = PlanGenerator(llm_client=mock_llm, available_tools=mock_tools)

        assert generator.llm_client == mock_llm
        assert generator.available_tools == mock_tools
        assert generator.max_steps == 10

    def test_init_with_custom_max_steps(self) -> None:
        """Test creating PlanGenerator with custom max_steps."""
        mock_llm = AsyncMock()

        generator = PlanGenerator(
            llm_client=mock_llm,
            available_tools=[],
            max_steps=20,
        )

        assert generator.max_steps == 20

    def test_init_with_empty_tools(self) -> None:
        """Test creating PlanGenerator with no tools."""
        mock_llm = AsyncMock()

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        assert generator.available_tools == []


class TestToolDescriptions:
    """Tests for tool description formatting."""

    def test_format_tool_descriptions_empty(self) -> None:
        """Test formatting with no tools."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        result = generator._format_tool_descriptions()

        assert result == "No tools available"

    def test_format_tool_descriptions_single_tool(self) -> None:
        """Test formatting with single tool."""
        mock_llm = AsyncMock()
        mock_tool = Mock()
        mock_tool.name = "TestTool"
        mock_tool.description = "A test tool"

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[mock_tool])

        result = generator._format_tool_descriptions()

        assert "TestTool" in result
        assert "A test tool" in result

    def test_format_tool_descriptions_multiple_tools(self) -> None:
        """Test formatting with multiple tools."""
        mock_llm = AsyncMock()
        mock_tool1 = Mock()
        mock_tool1.name = "MemorySearch"
        mock_tool1.description = "Search memory"

        mock_tool2 = Mock()
        mock_tool2.name = "EntityLookup"
        mock_tool2.description = "Lookup entities"

        generator = PlanGenerator(
            llm_client=mock_llm,
            available_tools=[mock_tool1, mock_tool2],
        )

        result = generator._format_tool_descriptions()

        assert "MemorySearch" in result
        assert "Search memory" in result
        assert "EntityLookup" in result
        assert "Lookup entities" in result


class TestBuildSystemPrompt:
    """Tests for system prompt building."""

    def test_build_system_prompt_includes_tools(self) -> None:
        """Test that system prompt includes tool descriptions."""
        mock_llm = AsyncMock()
        mock_tool = Mock()
        mock_tool.name = "TestTool"
        mock_tool.description = "Test description"

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[mock_tool])

        prompt = generator._build_system_prompt()

        assert "TestTool" in prompt
        assert "Test description" in prompt
        assert "structured execution plan" in prompt.lower()

    def test_build_system_prompt_includes_max_steps(self) -> None:
        """Test that system prompt includes max_steps."""
        mock_llm = AsyncMock()

        generator = PlanGenerator(
            llm_client=mock_llm,
            available_tools=[],
            max_steps=15,
        )

        prompt = generator._build_system_prompt()

        assert "15" in prompt


class TestBuildUserPrompt:
    """Tests for user prompt building."""

    def test_build_user_prompt_with_context(self) -> None:
        """Test building user prompt with context."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        prompt = generator._build_user_prompt(
            query="Search for Python memories",
            context="Project: AI research\nTopic: Python",
        )

        assert "Search for Python memories" in prompt
        assert "Project: AI research" in prompt
        assert "Topic: Python" in prompt

    def test_build_user_prompt_without_context(self) -> None:
        """Test building user prompt without context."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        prompt = generator._build_user_prompt(
            query="Search memories",
            context=None,
        )

        assert "Search memories" in prompt
        # Prompt should contain context section with "No specific context"
        assert "Context:" in prompt


class TestParseLLMResponse:
    """Tests for LLM response parsing."""

    def test_parse_plain_json_response(self) -> None:
        """Test parsing plain JSON response."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        json_response = '''{"steps": [
            {
                "description": "Search memory",
                "action_type": "tool",
                "tool_name": "MemorySearch",
                "input_data": {"query": "test"},
                "expected_output": "Results",
                "dependencies": [],
                "estimated_duration_ms": 3000
            }
        ]}'''

        result = generator._parse_llm_response(json_response)

        assert "steps" in result
        assert len(result["steps"]) == 1
        assert result["steps"][0]["description"] == "Search memory"

    def test_parse_markdown_json_response(self) -> None:
        """Test parsing JSON wrapped in markdown code blocks."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        markdown_response = '''Here is the plan:

```json
{
    "steps": [
        {
            "description": "Search memory",
            "action_type": "tool",
            "tool_name": "MemorySearch",
            "input_data": {"query": "test"},
            "expected_output": "Results",
            "dependencies": [],
            "estimated_duration_ms": 3000
        }
    ]
}
```

This plan should work.'''

        result = generator._parse_llm_response(markdown_response)

        assert "steps" in result
        assert len(result["steps"]) == 1

    def test_parse_response_with_invalid_json_raises_error(self) -> None:
        """Test that invalid JSON raises appropriate error."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        with pytest.raises(ValueError, match="Failed to parse plan"):
            generator._parse_llm_response("This is not JSON")

    def test_parse_response_with_missing_steps_raises_error(self) -> None:
        """Test that JSON without 'steps' key raises error."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        with pytest.raises(ValueError, match="Missing 'steps'"):
            generator._parse_llm_response('{"data": []}')


class TestMapDependencies:
    """Tests for dependency mapping."""

    def test_map_dependencies_empty(self) -> None:
        """Test mapping with no dependencies."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        step_indices = {"step-0": 0, "step-1": 1}
        deps = generator._map_dependencies([], step_indices)

        assert deps == []

    def test_map_dependencies_with_indices(self) -> None:
        """Test mapping step indices to step IDs."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        step_indices = {"step-0": 0, "step-1": 1, "step-2": 2}

        deps = generator._map_dependencies([0, 1], step_indices)

        assert deps == ["step-0", "step-1"]

    def test_map_dependencies_with_invalid_index(self) -> None:
        """Test mapping with non-existent index returns empty list for that dep."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        step_indices = {"step-0": 0}

        deps = generator._map_dependencies([0, 5], step_indices)

        # Only valid index should be mapped
        assert deps == ["step-0"]


class TestCreateExecutionSteps:
    """Tests for creating ExecutionStep instances."""

    def test_create_execution_steps_from_raw_data(self) -> None:
        """Test creating steps from raw LLM output."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        raw_steps = [
            {
                "description": "Search memory",
                "action_type": "tool",
                "tool_name": "MemorySearch",
                "input_data": {"query": "Python"},
                "expected_output": "Results",
                "dependencies": [],
                "estimated_duration_ms": 3000,
            },
            {
                "description": "Summarize",
                "action_type": "tool",
                "tool_name": "Summary",
                "input_data": {"content": "previous result"},
                "expected_output": "Summary",
                "dependencies": [0],
                "estimated_duration_ms": 5000,
            },
        ]

        steps = generator._create_execution_steps(raw_steps)

        assert len(steps) == 2
        assert steps[0].description == "Search memory"
        assert steps[0].tool_name == "MemorySearch"
        assert steps[0].tool_input == {"query": "Python"}
        assert steps[0].dependencies == []
        assert steps[0].status == ExecutionStepStatus.PENDING

        # Second step should depend on first step (by step_id, not step-0)
        assert len(steps[1].dependencies) == 1

    def test_create_execution_step_with_think_action(self) -> None:
        """Test creating a 'think' step without tool."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        raw_steps = [
            {
                "description": "Analyze the request",
                "action_type": "think",
                "tool_name": None,
                "input_data": {},
                "expected_output": "Analysis",
                "dependencies": [],
                "estimated_duration_ms": 2000,
            },
        ]

        steps = generator._create_execution_steps(raw_steps)

        assert len(steps) == 1
        # Think steps use a special tool name or None
        assert steps[0].description == "Analyze the request"


class TestGeneratePlan:
    """Tests for the main generate_plan method (integration of all components)."""

    @pytest.mark.asyncio
    async def test_generate_plan_success(self) -> None:
        """Test successful plan generation."""
        response = '''```json
{
    "steps": [
        {
            "description": "Search memory for Python",
            "action_type": "tool",
            "tool_name": "MemorySearch",
            "input_data": {"query": "Python"},
            "expected_output": "Relevant memories",
            "dependencies": [],
            "estimated_duration_ms": 3000
        },
        {
            "description": "Summarize findings",
            "action_type": "tool",
            "tool_name": "Summary",
            "input_data": {"content": "$previous_result"},
            "expected_output": "Summary of Python learnings",
            "dependencies": [0],
            "estimated_duration_ms": 5000
        }
    ]
}
```'''

        mock_llm = create_mock_llm(response)
        mock_tool1 = Mock()
        mock_tool1.name = "MemorySearch"
        mock_tool1.description = "Search memory"

        mock_tool2 = Mock()
        mock_tool2.name = "Summary"
        mock_tool2.description = "Summarize content"

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[mock_tool1, mock_tool2])

        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Summarize what I know about Python",
            context="Project: AI research",
        )

        assert isinstance(plan, ExecutionPlan)
        assert plan.conversation_id == "conv-1"
        assert plan.user_query == "Summarize what I know about Python"
        assert len(plan.steps) == 2
        assert plan.status == ExecutionPlanStatus.DRAFT
        assert plan.steps[0].description == "Search memory for Python"
        # Check dependency is set (actual step ID will be UUID-based)
        assert len(plan.steps[1].dependencies) == 1

        # Verify LLM was called with proper prompts
        assert mock_llm.generate.call_count == 1

    @pytest.mark.asyncio
    async def test_generate_plan_with_plain_json(self) -> None:
        """Test plan generation with plain JSON response (no markdown)."""
        response = '''{"steps": [
            {
                "description": "Test step",
                "action_type": "tool",
                "tool_name": "TestTool",
                "input_data": {},
                "expected_output": "Output",
                "dependencies": [],
                "estimated_duration_ms": 1000
            }
        ]}'''

        mock_llm = create_mock_llm(response)
        mock_tool = Mock()
        mock_tool.name = "TestTool"

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[mock_tool])

        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Test query",
        )

        assert len(plan.steps) == 1
        assert "Test step" in plan.steps[0].description

    @pytest.mark.asyncio
    async def test_generate_plan_with_empty_steps(self) -> None:
        """Test plan generation with empty steps in response."""
        response = '''{"steps": []}'''

        mock_llm = create_mock_llm(response)
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Test query",
            context=None,
        )

        # Empty steps is valid - plan with no actions
        assert len(plan.steps) == 0

    @pytest.mark.asyncio
    async def test_generate_plan_llm_error_uses_fallback(self) -> None:
        """Test that LLM error triggers fallback plan generation."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM service unavailable"))

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Search memories about Python",
        )

        # Should return a fallback plan
        assert isinstance(plan, ExecutionPlan)
        assert plan.conversation_id == "conv-1"
        assert len(plan.steps) >= 1  # Fallback should have at least one step
        # Fallback for search query should have search or analyze in description
        assert any(keyword in plan.steps[0].description.lower()
                   for keyword in ["search", "analyze", "clarify", "memories"])

    @pytest.mark.asyncio
    async def test_generate_plan_invalid_json_uses_fallback(self) -> None:
        """Test that invalid JSON triggers fallback plan generation."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="This is not valid JSON at all")

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Test query",
        )

        # Should return a fallback plan
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) >= 1

    @pytest.mark.asyncio
    async def test_generate_plan_with_reflection_disabled(self) -> None:
        """Test generating plan with reflection disabled."""
        response = '''{"steps": [
            {
                "description": "Test step",
                "action_type": "tool",
                "tool_name": "TestTool",
                "input_data": {},
                "expected_output": "Output",
                "dependencies": [],
                "estimated_duration_ms": 1000
            }
        ]}'''

        mock_llm = create_mock_llm(response)
        mock_tool = Mock()
        mock_tool.name = "TestTool"

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[mock_tool])

        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Test query",
            reflection_enabled=False,
        )

        assert plan.reflection_enabled is False


class TestGenerateFallbackPlan:
    """Tests for fallback plan generation."""

    def test_generate_fallback_plan_creates_basic_steps(self) -> None:
        """Test that fallback creates a basic plan."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        plan = generator._generate_fallback_plan(
            conversation_id="conv-1",
            query="Search for information",
        )

        assert isinstance(plan, ExecutionPlan)
        assert plan.conversation_id == "conv-1"
        assert len(plan.steps) >= 1

    def test_generate_fallback_plan_for_search_query(self) -> None:
        """Test fallback for search-type queries."""
        mock_llm = AsyncMock()
        mock_tool = Mock()
        mock_tool.name = "MemorySearch"
        mock_tool.description = "Search memories"

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[mock_tool])

        plan = generator._generate_fallback_plan(
            conversation_id="conv-1",
            query="Search my memories about Python",
        )

        # Should create a MemorySearch step
        search_steps = [s for s in plan.steps if "search" in s.description.lower()]
        assert len(search_steps) >= 1

    def test_generate_fallback_plan_for_unknown_query(self) -> None:
        """Test fallback for generic queries."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        plan = generator._generate_fallback_plan(
            conversation_id="conv-1",
            query="Help me with something",
        )

        # Should create a general analysis step
        assert len(plan.steps) >= 1
        assert any("analyze" in s.description.lower() or "determine" in s.description.lower()
                   for s in plan.steps)


class TestValidateToolAvailability:
    """Tests for tool availability validation."""

    def test_validate_tool_available(self) -> None:
        """Test validation when tool is available."""
        mock_llm = AsyncMock()
        mock_tool = Mock()
        mock_tool.name = "MemorySearch"

        generator = PlanGenerator(llm_client=mock_llm, available_tools=[mock_tool])

        is_valid = generator._validate_tool_availability("MemorySearch")

        assert is_valid is True

    def test_validate_tool_not_available(self) -> None:
        """Test validation when tool is not available."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        is_valid = generator._validate_tool_availability("UnknownTool")

        assert is_valid is False

    def test_validate_tool_none_for_think_steps(self) -> None:
        """Test that None tool_name is valid for think steps."""
        mock_llm = AsyncMock()
        generator = PlanGenerator(llm_client=mock_llm, available_tools=[])

        is_valid = generator._validate_tool_availability(None)

        assert is_valid is True
