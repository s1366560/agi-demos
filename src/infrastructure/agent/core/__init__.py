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
    "ProcessorConfig",
    "ProjectAgentConfig",
    "ProjectAgentManager",
    "ProjectAgentMetrics",
    "ProjectAgentStatus",
    # Project-level agent
    "ProjectReActAgent",
    # Core agent
    "ReActAgent",
    # Session processing
    "SessionProcessor",
    "ToolDefinition",
    "create_react_agent",
    "get_project_agent_manager",
    "stop_project_agent_manager",
]
