"""
ReAct Agent Core Module.

This module provides the core ReAct agent implementation including:
- ReActAgent: Main agent class with streaming support
- ProjectReActAgent: Project-scoped agent with lifecycle management
- ProjectAgentManager: Manager for multiple project agents
- SessionProcessor: Low-level session processing
- ToolDefinition: Tool interface definitions
"""

from .processor import ProcessorConfig, SessionProcessor, ToolDefinition
from .project_react_agent import (
    ProjectAgentConfig,
    ProjectAgentManager,
    ProjectAgentMetrics,
    ProjectAgentStatus,
    ProjectReActAgent,
    get_project_agent_manager,
    stop_project_agent_manager,
)
from .react_agent import ReActAgent, create_react_agent

__all__ = [
    # Core agent
    "ReActAgent",
    "create_react_agent",
    # Project-level agent
    "ProjectReActAgent",
    "ProjectAgentConfig",
    "ProjectAgentStatus",
    "ProjectAgentMetrics",
    "ProjectAgentManager",
    "get_project_agent_manager",
    "stop_project_agent_manager",
    # Session processing
    "SessionProcessor",
    "ProcessorConfig",
    "ToolDefinition",
]
