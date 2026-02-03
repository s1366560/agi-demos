"""
Unit tests for WorkPlanGenerator.

Tests the work plan generation logic extracted from SessionProcessor.
"""

from dataclasses import dataclass

import pytest

from src.infrastructure.agent.planning.work_plan_generator import (
    PlanStep,
    QueryAnalysis,
    WorkPlan,
    WorkPlanGenerator,
    classify_tool_by_description,
    get_work_plan_generator,
    set_work_plan_generator,
)

# ============================================================
# Test Fixtures
# ============================================================


@pytest.fixture
def generator():
    """Create a fresh WorkPlanGenerator instance."""
    return WorkPlanGenerator(debug_logging=False)


@pytest.fixture
def debug_generator():
    """Create a WorkPlanGenerator with debug logging."""
    return WorkPlanGenerator(debug_logging=True)


@dataclass
class MockToolDefinition:
    """Mock tool definition for testing."""

    description: str


@pytest.fixture
def search_tools():
    """Sample search tools."""
    return {
        "web_search": MockToolDefinition(description="Search the web for information"),
        "bing_search": MockToolDefinition(description="Search using Bing web API"),
    }


@pytest.fixture
def memory_tools():
    """Sample memory tools."""
    return {
        "memory_search": MockToolDefinition(description="Search episodic memory store"),
        "knowledge_query": MockToolDefinition(description="Query knowledge base"),
    }


@pytest.fixture
def code_tools():
    """Sample code execution tools."""
    return {
        "python_exec": MockToolDefinition(description="Execute Python code"),
        "run_script": MockToolDefinition(description="Run a script file"),
    }


@pytest.fixture
def mixed_tools(search_tools, memory_tools, code_tools):
    """Combined tools from all categories."""
    return {**search_tools, **memory_tools, **code_tools}


# ============================================================
# Test Tool Classification
# ============================================================


@pytest.mark.unit
class TestToolClassification:
    """Test classify_tool_by_description function."""

    def test_classify_search_tool(self):
        """Test classifying web search tools."""
        result = classify_tool_by_description(
            "web_search", "Search the web for information"
        )
        assert result == "search"

    def test_classify_scrape_tool(self):
        """Test classifying web scraping tools."""
        result = classify_tool_by_description(
            "web_scraper", "Scrape content from web pages"
        )
        assert result == "scrape"

    def test_classify_memory_tool(self):
        """Test classifying memory tools."""
        result = classify_tool_by_description(
            "memory_search", "Search episodic memory for past events"
        )
        assert result == "memory"

    def test_classify_entity_tool(self):
        """Test classifying entity lookup tools."""
        result = classify_tool_by_description(
            "entity_lookup", "Lookup entities in the graph"
        )
        assert result == "entity"

    def test_classify_graph_tool(self):
        """Test classifying graph query tools."""
        result = classify_tool_by_description(
            "graph_query", "Execute Cypher queries on graph database"
        )
        assert result == "graph"

    def test_classify_code_tool(self):
        """Test classifying code execution tools."""
        result = classify_tool_by_description(
            "python_exec", "Execute Python code in sandbox"
        )
        assert result == "code"

    def test_classify_summary_tool(self):
        """Test classifying summarization tools."""
        result = classify_tool_by_description(
            "summarize", "Summarize long text content"
        )
        assert result == "summary"

    def test_classify_unknown_tool(self):
        """Test classifying unknown tool type."""
        result = classify_tool_by_description(
            "custom_tool", "A custom tool that does something"
        )
        assert result == "other"


# ============================================================
# Test QueryAnalysis
# ============================================================


@pytest.mark.unit
class TestQueryAnalysis:
    """Test QueryAnalysis dataclass."""

    def test_has_tool_needs_true(self):
        """Test has_tool_needs when needs are present."""
        analysis = QueryAnalysis(needs_search=True)
        assert analysis.has_tool_needs is True

    def test_has_tool_needs_false(self):
        """Test has_tool_needs when no needs."""
        analysis = QueryAnalysis()
        assert analysis.has_tool_needs is False

    def test_multiple_needs(self):
        """Test with multiple needs."""
        analysis = QueryAnalysis(
            needs_search=True,
            needs_memory=True,
            needs_summary=True,
        )
        assert analysis.has_tool_needs is True


# ============================================================
# Test PlanStep
# ============================================================


@pytest.mark.unit
class TestPlanStep:
    """Test PlanStep dataclass."""

    def test_to_dict(self):
        """Test converting step to dictionary."""
        step = PlanStep(
            step_number=0,
            description="Search for information",
            required_tools=["web_search"],
            status="pending",
        )

        result = step.to_dict()

        assert result["step_number"] == 0
        assert result["description"] == "Search for information"
        assert result["required_tools"] == ["web_search"]
        assert result["status"] == "pending"

    def test_default_values(self):
        """Test default values."""
        step = PlanStep(step_number=1, description="Test")

        assert step.required_tools == []
        assert step.status == "pending"


# ============================================================
# Test WorkPlan
# ============================================================


@pytest.mark.unit
class TestWorkPlan:
    """Test WorkPlan dataclass."""

    def test_total_steps(self):
        """Test total_steps property."""
        plan = WorkPlan(
            plan_id="test-123",
            steps=[
                PlanStep(0, "Step 1"),
                PlanStep(1, "Step 2"),
                PlanStep(2, "Step 3"),
            ],
        )
        assert plan.total_steps == 3

    def test_is_empty_true(self):
        """Test is_empty when plan has only final step."""
        plan = WorkPlan(
            plan_id="test-123",
            steps=[PlanStep(0, "Final step")],
        )
        assert plan.is_empty is True

    def test_is_empty_false(self):
        """Test is_empty when plan has meaningful steps."""
        plan = WorkPlan(
            plan_id="test-123",
            steps=[
                PlanStep(0, "Search"),
                PlanStep(1, "Final"),
            ],
        )
        assert plan.is_empty is False

    def test_get_step_for_tool(self):
        """Test getting step index for a tool."""
        plan = WorkPlan(
            plan_id="test-123",
            steps=[PlanStep(0, "Search")],
            tool_to_step_mapping={"web_search": 0, "memory_search": 1},
        )

        assert plan.get_step_for_tool("web_search") == 0
        assert plan.get_step_for_tool("memory_search") == 1
        assert plan.get_step_for_tool("unknown") is None

    def test_to_dict(self):
        """Test converting plan to dictionary."""
        plan = WorkPlan(
            plan_id="test-123",
            steps=[
                PlanStep(0, "Search", ["web_search"]),
                PlanStep(1, "Final"),
            ],
            current_step=0,
        )

        result = plan.to_dict(conversation_id="conv-456")

        assert result["plan_id"] == "test-123"
        assert result["conversation_id"] == "conv-456"
        assert result["status"] == "in_progress"
        assert len(result["steps"]) == 2
        assert result["current_step"] == 0
        assert result["total_steps"] == 2


# ============================================================
# Test WorkPlanGenerator.generate
# ============================================================


@pytest.mark.unit
class TestWorkPlanGeneratorGenerate:
    """Test WorkPlanGenerator.generate method."""

    def test_generate_returns_none_when_no_tools(self, generator):
        """Test that generate returns None when no tools provided."""
        result = generator.generate("Search for AI news", tools={})
        assert result is None

    def test_generate_with_search_query(self, generator, search_tools):
        """Test generating plan for search query."""
        plan = generator.generate("搜索最近的 AI 新闻", tools=search_tools)

        assert plan is not None
        assert not plan.is_empty
        # Should have search step + final step
        assert len(plan.steps) >= 2
        assert "搜索" in plan.steps[0].description

    def test_generate_with_memory_query(self, generator, memory_tools):
        """Test generating plan for memory query."""
        plan = generator.generate("查找我的记忆中关于会议的记录", tools=memory_tools)

        assert plan is not None
        assert not plan.is_empty

    def test_generate_with_code_query(self, generator, code_tools):
        """Test generating plan for code execution query."""
        plan = generator.generate("执行这段 Python 代码", tools=code_tools)

        assert plan is not None
        assert not plan.is_empty

    def test_generate_simple_query_returns_none(self, generator, mixed_tools):
        """Test that simple queries without tool keywords return None."""
        plan = generator.generate("你好，今天天气怎么样？", tools=mixed_tools)

        # Simple greeting shouldn't need a work plan
        assert plan is None

    def test_generate_multi_step_plan(self, generator, mixed_tools):
        """Test generating plan with multiple steps."""
        plan = generator.generate(
            "搜索最新新闻然后总结", tools={
                **mixed_tools,
                "summarize": MockToolDefinition(description="Summarize text content"),
            }
        )

        assert plan is not None
        # Should have multiple steps before final
        assert len(plan.steps) >= 2

    def test_generate_assigns_unique_plan_id(self, generator, search_tools):
        """Test that each plan gets a unique ID."""
        plan1 = generator.generate("搜索 AI", tools=search_tools)
        plan2 = generator.generate("搜索 ML", tools=search_tools)

        assert plan1.plan_id != plan2.plan_id

    def test_generate_tool_mapping(self, generator, search_tools):
        """Test that tools are properly mapped to steps."""
        plan = generator.generate("搜索最新消息", tools=search_tools)

        assert plan is not None
        # Search tools should be mapped to a step
        for tool_name in search_tools.keys():
            assert tool_name in plan.tool_to_step_mapping


# ============================================================
# Test Query Analysis
# ============================================================


@pytest.mark.unit
class TestQueryAnalysisInGenerator:
    """Test query analysis within generator."""

    def test_detects_search_keywords(self, generator):
        """Test detection of search keywords."""
        analysis = generator._analyze_query("search for information")
        assert analysis.needs_search is True

    def test_detects_chinese_search_keywords(self, generator):
        """Test detection of Chinese search keywords."""
        analysis = generator._analyze_query("搜索相关资料")
        assert analysis.needs_search is True

    def test_detects_scrape_keywords(self, generator):
        """Test detection of scrape keywords."""
        analysis = generator._analyze_query("抓取这个网站的内容")
        assert analysis.needs_scrape is True

    def test_detects_memory_keywords(self, generator):
        """Test detection of memory keywords."""
        analysis = generator._analyze_query("查找我的记忆")
        assert analysis.needs_memory is True

    def test_detects_graph_keywords(self, generator):
        """Test detection of graph keywords."""
        analysis = generator._analyze_query("查询知识图谱中的实体")
        assert analysis.needs_graph is True

    def test_detects_code_keywords(self, generator):
        """Test detection of code keywords."""
        analysis = generator._analyze_query("执行这段 Python 代码")
        assert analysis.needs_code is True

    def test_detects_summary_keywords(self, generator):
        """Test detection of summary keywords."""
        analysis = generator._analyze_query("总结这篇文章")
        assert analysis.needs_summary is True


# ============================================================
# Test Singleton Functions
# ============================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_work_plan_generator(self):
        """Test getting default generator."""
        gen = get_work_plan_generator()
        assert isinstance(gen, WorkPlanGenerator)

    def test_get_returns_same_instance(self):
        """Test that getter returns same instance."""
        gen1 = get_work_plan_generator()
        gen2 = get_work_plan_generator()
        assert gen1 is gen2

    def test_set_work_plan_generator(self):
        """Test setting custom generator."""
        custom = WorkPlanGenerator(debug_logging=True)
        set_work_plan_generator(custom)

        result = get_work_plan_generator()
        assert result is custom

        # Cleanup
        set_work_plan_generator(WorkPlanGenerator())


# ============================================================
# Test Edge Cases
# ============================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_query(self, generator, search_tools):
        """Test handling empty query."""
        plan = generator.generate("", tools=search_tools)
        # Empty query shouldn't match any keywords
        assert plan is None

    def test_tools_without_description(self, generator):
        """Test handling tools without description attribute."""

        class MinimalTool:
            description = ""

        tools = {"tool1": MinimalTool()}
        plan = generator.generate("搜索信息", tools=tools)

        # Should still work, just classify as 'other'
        assert plan is None  # No matching tools for search

    def test_debug_logging_enabled(self, debug_generator, search_tools, caplog):
        """Test that debug logging produces output."""
        import logging

        caplog.set_level(logging.INFO)

        debug_generator.generate("搜索最新新闻", tools=search_tools)

        assert any("WorkPlanGenerator" in record.message for record in caplog.records)

    def test_custom_tool_classifier(self):
        """Test using custom tool classifier."""

        def custom_classifier(name: str, desc: str) -> str:
            return "custom" if "custom" in name else "other"

        generator = WorkPlanGenerator(tool_classifier=custom_classifier)

        tools = {
            "custom_tool": MockToolDefinition(description="A custom tool"),
            "regular_tool": MockToolDefinition(description="A regular tool"),
        }

        # Categorize tools
        categories = generator._categorize_tools(tools)

        assert "custom" in categories
        assert "custom_tool" in categories["custom"]

    def test_get_step_description(self, generator, search_tools):
        """Test getting step description."""
        plan = generator.generate("搜索信息", tools=search_tools)

        if plan:
            desc = generator.get_step_description(0, plan)
            assert desc == plan.steps[0].description

    def test_get_step_description_invalid_index(self, generator, search_tools):
        """Test getting step description with invalid index."""
        plan = generator.generate("搜索信息", tools=search_tools)

        if plan:
            desc = generator.get_step_description(999, plan)
            assert desc == "Step 999"

    def test_very_long_query(self, generator, search_tools):
        """Test handling very long query."""
        long_query = "搜索 " + "a" * 10000
        plan = generator.generate(long_query, tools=search_tools)

        # Should still work
        assert plan is not None
