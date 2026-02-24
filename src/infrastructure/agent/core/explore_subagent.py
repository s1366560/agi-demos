"""
Explore SubAgent for Plan Mode.

This module provides a specialized SubAgent for code exploration during Plan Mode.
The explore-agent has read-only access and is used to gather information about
the codebase before implementation.
"""

import uuid
from datetime import UTC, datetime

from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent

# Default explore-agent configuration
EXPLORE_AGENT_SYSTEM_PROMPT = """You are an expert code explorer and analyst.

Your task is to explore and analyze the codebase to gather information for planning.
You have READ-ONLY access to the codebase - you cannot modify any files.

Key responsibilities:
1. Search for relevant files using glob patterns
2. Read and understand code structure
3. Identify patterns and conventions in the codebase
4. Find related implementations that can serve as references
5. Document your findings clearly

When exploring:
- Start with broad searches to understand the structure
- Drill down into specific files for detailed understanding
- Look for existing patterns that should be followed
- Identify dependencies and relationships between components
- Note any conventions (naming, file organization, etc.)

Always provide clear, structured summaries of your findings that will help
with implementation planning.

IMPORTANT: You are in EXPLORE mode and cannot modify any files. Focus on
gathering information and understanding the codebase."""

EXPLORE_AGENT_TRIGGER = AgentTrigger(
    description="Explore and analyze the codebase to gather information for planning",
    examples=[
        "Find all files related to user authentication",
        "What patterns are used for API endpoints?",
        "How is the database connection managed?",
        "Search for existing implementations of caching",
        "Understand the project structure",
    ],
    keywords=[
        "explore",
        "search",
        "find",
        "look for",
        "understand",
        "analyze",
        "investigate",
        "codebase",
        "structure",
        "pattern",
    ],
)

EXPLORE_AGENT_ALLOWED_TOOLS = [
    "glob",
    "grep",
    "read",
    "memory_search",
    "entity_lookup",
    "episode_retrieval",
    "graph_query",
    "web_search",
    "web_scrape",
]


def create_explore_subagent(
    tenant_id: str,
    project_id: str | None = None,
    model: AgentModel = AgentModel.INHERIT,
    additional_tools: list[str] | None = None,
) -> SubAgent:
    """
    Create an explore SubAgent for Plan Mode.

    Args:
        tenant_id: The tenant ID
        project_id: Optional project ID for project-specific exploration
        model: LLM model to use (defaults to INHERIT)
        additional_tools: Additional tools to allow

    Returns:
        A configured explore SubAgent
    """
    allowed_tools = list(EXPLORE_AGENT_ALLOWED_TOOLS)
    if additional_tools:
        allowed_tools.extend(additional_tools)

    return SubAgent(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        project_id=project_id,
        name="explore-agent",
        display_name="Code Explorer",
        system_prompt=EXPLORE_AGENT_SYSTEM_PROMPT,
        trigger=EXPLORE_AGENT_TRIGGER,
        model=model,
        color="#722ed1",  # Purple for exploration
        allowed_tools=allowed_tools,
        allowed_skills=[],
        allowed_mcp_servers=[],
        max_tokens=4096,
        temperature=0.3,  # Lower temperature for more consistent exploration
        max_iterations=20,
        enabled=True,
        total_invocations=0,
        avg_execution_time_ms=0.0,
        success_rate=1.0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def get_explore_agent_template() -> dict:
    """
    Get the explore-agent template for UI display.

    Returns:
        Template dictionary with name, display_name, and description
    """
    return {
        "name": "explore-agent",
        "display_name": "Code Explorer",
        "description": "Specialized agent for exploring and analyzing codebases during Plan Mode",
        "category": "planning",
    }
