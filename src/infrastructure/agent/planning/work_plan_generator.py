"""
Work Plan Generator - Generate execution plans for ReAct agent.

This module provides centralized work plan generation logic, extracted from
SessionProcessor to support the Single Responsibility Principle.

Handles:
- Analyzing user queries to predict tool usage
- Classifying tools by semantic purpose
- Building step-by-step execution plans
- Managing tool-to-step mappings

Reference: Extracted from processor.py::_generate_work_plan() (lines 370-553)
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Set

logger = logging.getLogger(__name__)


# ============================================================
# Tool Classification
# ============================================================


def classify_tool_by_description(tool_name: str, description: str) -> str:
    """
    Classify tool into a category based on its description.

    Uses semantic keywords in the tool's description to determine its purpose,
    supporting dynamic tool addition via MCP or Skills without hardcoded names.

    Args:
        tool_name: Name of the tool
        description: Tool description

    Returns:
        Category string: "search", "scrape", "memory", "entity", "graph",
                         "code", "summary", "other"
    """
    desc_lower = description.lower()

    # Search tools: find information from web, databases, etc.
    search_keywords = ["search", "搜索", "查找", "find", "query", "查询", "bing", "google"]
    if any(kw in desc_lower for kw in search_keywords) and "web" in desc_lower:
        return "search"

    # Scrape tools: extract content from web pages
    scrape_keywords = ["scrape", "抓取", "extract", "提取", "fetch", "获取", "crawl", "爬取"]
    if any(kw in desc_lower for kw in scrape_keywords) and any(
        w in desc_lower for w in ["web", "page", "网页", "html", "url"]
    ):
        return "scrape"

    # Memory tools: access knowledge base
    memory_keywords = ["memory", "记忆", "knowledge", "知识", "recall", "回忆", "episodic"]
    if any(kw in desc_lower for kw in memory_keywords):
        return "memory"

    # Entity tools: lookup entities in knowledge graph
    entity_keywords = ["entity", "实体", "lookup", "查找实体"]
    if any(kw in desc_lower for kw in entity_keywords):
        return "entity"

    # Graph tools: query knowledge graph
    graph_keywords = ["graph", "图谱", "cypher", "traversal", "遍历", "关系"]
    if any(kw in desc_lower for kw in graph_keywords):
        return "graph"

    # Code execution tools
    code_keywords = ["execute", "执行", "run", "运行", "code", "代码", "python", "script"]
    if any(kw in desc_lower for kw in code_keywords):
        return "code"

    # Summary tools
    summary_keywords = ["summarize", "总结", "summary", "概括", "归纳", "digest"]
    if any(kw in desc_lower for kw in summary_keywords):
        return "summary"

    return "other"


# ============================================================
# Data Classes
# ============================================================


@dataclass
class PlanStep:
    """
    Represents a single step in a work plan.

    Attributes:
        step_number: Sequential step index (0-based)
        description: Human-readable description of the step
        required_tools: List of tool names that may be used in this step
        status: Current status ('pending', 'in_progress', 'completed', 'skipped')
    """

    step_number: int
    description: str
    required_tools: List[str] = field(default_factory=list)
    status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "step_number": self.step_number,
            "description": self.description,
            "required_tools": self.required_tools,
            "status": self.status,
        }


@dataclass
class QueryAnalysis:
    """
    Analysis of user query to determine required capabilities.

    Attributes:
        needs_search: Query requires web search
        needs_scrape: Query requires web scraping
        needs_summary: Query requires summarization
        needs_memory: Query requires memory/knowledge access
        needs_graph: Query requires knowledge graph operations
        needs_code: Query requires code execution
    """

    needs_search: bool = False
    needs_scrape: bool = False
    needs_summary: bool = False
    needs_memory: bool = False
    needs_graph: bool = False
    needs_code: bool = False

    @property
    def has_tool_needs(self) -> bool:
        """Check if any tool usage is predicted."""
        return any(
            [
                self.needs_search,
                self.needs_scrape,
                self.needs_summary,
                self.needs_memory,
                self.needs_graph,
                self.needs_code,
            ]
        )


@dataclass
class WorkPlan:
    """
    Complete work plan for agent execution.

    Attributes:
        plan_id: Unique identifier for this plan
        steps: List of PlanStep objects
        tool_to_step_mapping: Map of tool names to step indices
        current_step: Index of the currently executing step
    """

    plan_id: str
    steps: List[PlanStep] = field(default_factory=list)
    tool_to_step_mapping: Dict[str, int] = field(default_factory=dict)
    current_step: int = 0

    @property
    def total_steps(self) -> int:
        """Get total number of steps."""
        return len(self.steps)

    @property
    def is_empty(self) -> bool:
        """Check if plan has meaningful steps (beyond final synthesis)."""
        return len(self.steps) <= 1

    def get_step_for_tool(self, tool_name: str) -> Optional[int]:
        """Get the step index associated with a tool."""
        return self.tool_to_step_mapping.get(tool_name)

    def to_dict(self, conversation_id: str = "") -> Dict[str, Any]:
        """Convert to dictionary for SSE event."""
        return {
            "plan_id": self.plan_id,
            "conversation_id": conversation_id,
            "status": "in_progress",
            "steps": [step.to_dict() for step in self.steps],
            "current_step": self.current_step,
            "total_steps": self.total_steps,
        }


# ============================================================
# Tool Definition Protocol
# ============================================================


class ToolDefinitionLike(Protocol):
    """Protocol for tool definitions to avoid circular imports."""

    @property
    def description(self) -> str:
        ...


# ============================================================
# Work Plan Generator
# ============================================================


class WorkPlanGenerator:
    """
    Generates execution plans based on user queries and available tools.

    Creates transparent work plans that show users the expected execution flow
    of the ReAct agent, improving transparency and user experience.

    Usage:
        generator = WorkPlanGenerator()

        # Analyze query and generate plan
        plan = generator.generate(
            user_query="Search for recent news about AI",
            tools={"web_search": tool_def, "summarize": tool_def}
        )

        if plan and not plan.is_empty:
            # Use plan for SSE events
            event_data = plan.to_dict(conversation_id="conv-123")
    """

    # Query keywords for capability detection
    SEARCH_KEYWORDS = ["搜索", "search", "查找", "find", "查询"]
    SCRAPE_KEYWORDS = ["抓取", "scrape", "获取网页", "网站", "url", "http"]
    SUMMARY_KEYWORDS = ["总结", "summarize", "summary", "概括", "归纳"]
    MEMORY_KEYWORDS = ["记忆", "memory", "记录", "知识"]
    GRAPH_KEYWORDS = ["图谱", "graph", "实体", "entity", "关系"]
    CODE_KEYWORDS = ["代码", "code", "执行", "run", "python"]

    # Step descriptions by category
    STEP_DESCRIPTIONS = {
        "search": "搜索相关信息",
        "scrape": "获取网页内容",
        "memory": "搜索记忆库",
        "entity": "查询知识图谱实体",
        "graph": "执行图谱查询",
        "code": "执行代码",
        "summary": "总结分析结果",
        "final": "生成最终回复",
    }

    def __init__(
        self,
        tool_classifier: Optional[Callable[[str, str], str]] = None,
        debug_logging: bool = False,
    ):
        """
        Initialize the work plan generator.

        Args:
            tool_classifier: Optional custom tool classifier function.
                             Defaults to classify_tool_by_description.
            debug_logging: Whether to enable debug logging
        """
        self._tool_classifier = tool_classifier or classify_tool_by_description
        self._debug_logging = debug_logging

    def generate(
        self,
        user_query: str,
        tools: Dict[str, ToolDefinitionLike],
    ) -> Optional[WorkPlan]:
        """
        Generate a work plan based on user query and available tools.

        Args:
            user_query: The user's query
            tools: Dictionary of tool name -> tool definition

        Returns:
            WorkPlan object, or None if no tools available
        """
        if not tools:
            return None

        # Generate unique plan ID
        plan_id = str(uuid.uuid4())

        # Classify all available tools by their semantic purpose
        tool_categories = self._categorize_tools(tools)

        # Analyze query to predict likely tool usage
        analysis = self._analyze_query(user_query)

        # Build steps based on detected needs and categorized tools
        steps, tool_mapping = self._build_steps(analysis, tool_categories)

        plan = WorkPlan(
            plan_id=plan_id,
            steps=steps,
            tool_to_step_mapping=tool_mapping,
            current_step=0,
        )

        # If no specific tools detected (only final step), don't generate a work plan
        if plan.is_empty:
            if self._debug_logging:
                logger.info(
                    "[WorkPlanGenerator] No tool usage predicted, skipping plan generation"
                )
            return None

        if self._debug_logging:
            logger.info(
                f"[WorkPlanGenerator] Generated plan with {plan.total_steps} steps: "
                f"{[s.description for s in steps]}"
            )

        return plan

    def _categorize_tools(
        self, tools: Dict[str, ToolDefinitionLike]
    ) -> Dict[str, List[str]]:
        """
        Categorize tools by their semantic purpose.

        Args:
            tools: Dictionary of tool name -> tool definition

        Returns:
            Dictionary of category -> list of tool names
        """
        categories: Dict[str, List[str]] = {}

        for tool_name, tool_def in tools.items():
            description = tool_def.description if hasattr(tool_def, "description") else ""
            category = self._tool_classifier(tool_name, description)

            if category not in categories:
                categories[category] = []
            categories[category].append(tool_name)

        return categories

    def _analyze_query(self, user_query: str) -> QueryAnalysis:
        """
        Analyze user query to predict required capabilities.

        Args:
            user_query: The user's query

        Returns:
            QueryAnalysis with predicted needs
        """
        query_lower = user_query.lower()

        return QueryAnalysis(
            needs_search=any(kw in query_lower for kw in self.SEARCH_KEYWORDS),
            needs_scrape=any(kw in query_lower for kw in self.SCRAPE_KEYWORDS),
            needs_summary=any(kw in query_lower for kw in self.SUMMARY_KEYWORDS),
            needs_memory=any(kw in query_lower for kw in self.MEMORY_KEYWORDS),
            needs_graph=any(kw in query_lower for kw in self.GRAPH_KEYWORDS),
            needs_code=any(kw in query_lower for kw in self.CODE_KEYWORDS),
        )

    def _build_steps(
        self,
        analysis: QueryAnalysis,
        tool_categories: Dict[str, List[str]],
    ) -> tuple[List[PlanStep], Dict[str, int]]:
        """
        Build plan steps based on analysis and available tools.

        Args:
            analysis: Query analysis results
            tool_categories: Categorized tools

        Returns:
            Tuple of (list of PlanStep, tool-to-step mapping)
        """
        steps: List[PlanStep] = []
        tool_mapping: Dict[str, int] = {}
        step_number = 0

        # Define step building order
        step_configs = [
            (analysis.needs_search, "search", ["search"]),
            (analysis.needs_scrape, "scrape", ["scrape"]),
            (analysis.needs_memory, "memory", ["memory"]),
            (analysis.needs_graph, "entity", ["entity"]),
            (analysis.needs_graph, "graph", ["graph"]),
            (analysis.needs_code, "code", ["code"]),
            (analysis.needs_summary, "summary", ["summary"]),
        ]

        for needs, step_type, categories in step_configs:
            if not needs:
                continue

            # Collect tools from relevant categories
            relevant_tools: List[str] = []
            for category in categories:
                if category in tool_categories:
                    relevant_tools.extend(tool_categories[category])

            if not relevant_tools:
                continue

            # Create step
            steps.append(
                PlanStep(
                    step_number=step_number,
                    description=self.STEP_DESCRIPTIONS.get(step_type, f"执行 {step_type}"),
                    required_tools=relevant_tools,
                    status="pending",
                )
            )

            # Map tools to this step
            for tool_name in relevant_tools:
                tool_mapping[tool_name] = step_number

            step_number += 1

        # Always add a final synthesis step
        steps.append(
            PlanStep(
                step_number=step_number,
                description=self.STEP_DESCRIPTIONS["final"],
                required_tools=[],
                status="pending",
            )
        )

        return steps, tool_mapping

    def get_step_description(self, step_index: int, plan: WorkPlan) -> str:
        """
        Get human-readable description for a step.

        Args:
            step_index: Step index
            plan: Work plan

        Returns:
            Step description or default
        """
        if plan and step_index < len(plan.steps):
            return plan.steps[step_index].description
        return f"Step {step_index}"


# ============================================================
# Module-level Singleton
# ============================================================

_default_generator: Optional[WorkPlanGenerator] = None


def get_work_plan_generator() -> WorkPlanGenerator:
    """Get the default work plan generator singleton."""
    global _default_generator
    if _default_generator is None:
        _default_generator = WorkPlanGenerator()
    return _default_generator


def set_work_plan_generator(generator: WorkPlanGenerator) -> None:
    """Set the default work plan generator singleton."""
    global _default_generator
    _default_generator = generator
