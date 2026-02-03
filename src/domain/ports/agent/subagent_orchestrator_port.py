"""
SubAgent Orchestrator Port - Domain interface for sub-agent routing.

SubAgents are specialized agents (L3 layer) that handle specific
domains or tasks with their own tool sets and system prompts.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


class SubAgentType(str, Enum):
    """Types of sub-agents."""

    CODE = "code"  # Code generation/editing
    SEARCH = "search"  # Information retrieval
    ANALYSIS = "analysis"  # Data analysis
    PLANNING = "planning"  # Task planning
    CUSTOM = "custom"  # User-defined


@dataclass
class SubAgentMatchRequest:
    """Request to match a sub-agent.

    Attributes:
        message: User message to route
        project_id: Project context
        conversation_context: Recent conversation history
        available_subagents: List of available sub-agent configs
        metadata: Additional routing metadata
    """

    message: str
    project_id: str
    conversation_context: Optional[List[Dict[str, Any]]] = None
    available_subagents: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubAgentMatchResult:
    """Result of sub-agent matching.

    Attributes:
        matched: Whether a sub-agent was matched
        subagent_name: Name of matched sub-agent
        subagent_type: Type of sub-agent
        confidence: Match confidence (0-1)
        system_prompt: System prompt for sub-agent
        tools: Tools available to sub-agent
        config: Additional sub-agent configuration
    """

    matched: bool
    subagent_name: Optional[str] = None
    subagent_type: Optional[SubAgentType] = None
    confidence: float = 0.0
    system_prompt: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubAgentExecutionConfig:
    """Configuration for sub-agent execution.

    Attributes:
        max_steps: Maximum ReAct steps
        timeout: Execution timeout in seconds
        model: Model to use (overrides default)
        temperature: Sampling temperature
        tool_filter: Tools to include/exclude
    """

    max_steps: int = 10
    timeout: Optional[float] = None
    model: Optional[str] = None
    temperature: float = 0.7
    tool_filter: Optional[Dict[str, Any]] = None


@runtime_checkable
class SubAgentOrchestratorPort(Protocol):
    """
    Protocol for sub-agent orchestration.

    Handles routing messages to specialized sub-agents based on
    content analysis and configuration.

    Example:
        class SubAgentOrchestrator(SubAgentOrchestratorPort):
            async def match(
                self, request: SubAgentMatchRequest
            ) -> SubAgentMatchResult:
                # Analyze message to find matching sub-agent
                if self._is_code_task(request.message):
                    return SubAgentMatchResult(
                        matched=True,
                        subagent_name="code_agent",
                        subagent_type=SubAgentType.CODE,
                        ...
                    )
                return SubAgentMatchResult(matched=False)
    """

    async def match(self, request: SubAgentMatchRequest) -> SubAgentMatchResult:
        """
        Match a message to a sub-agent.

        Args:
            request: Match request with message and context

        Returns:
            Match result indicating if/which sub-agent matched
        """
        ...

    def get_execution_config(
        self, subagent_name: str
    ) -> SubAgentExecutionConfig:
        """
        Get execution configuration for a sub-agent.

        Args:
            subagent_name: Name of sub-agent

        Returns:
            Execution configuration
        """
        ...

    def filter_tools(
        self,
        tools: List[Dict[str, Any]],
        subagent_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Filter tools for a specific sub-agent.

        Args:
            tools: Full list of available tools
            subagent_name: Sub-agent to filter for

        Returns:
            Filtered list of tools
        """
        ...

    def get_available_subagents(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Get available sub-agents for a project.

        Args:
            project_id: Project to get sub-agents for

        Returns:
            List of sub-agent configurations
        """
        ...
