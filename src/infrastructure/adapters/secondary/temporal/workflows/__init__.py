"""
Temporal Workflows for MemStack.

This module provides Temporal workflow definitions for:
- Episode processing
- Entity deduplication
- Community rebuilding
- Agent execution
- Project-level agent sessions
"""

from .agent import AgentExecutionWorkflow, AgentInput, AgentState
from .agent_session import (
    AgentChatRequest,
    AgentChatResult,
    AgentSessionConfig,
    AgentSessionStatus,
    AgentSessionWorkflow,
    get_agent_session_workflow_id,
)
from .community import RebuildCommunitiesWorkflow
from .entity import DeduplicateEntitiesWorkflow
from .episode import EpisodeProcessingWorkflow, IncrementalRefreshWorkflow
from .project_agent_workflow import (
    ProjectAgentMetrics,
    ProjectAgentWorkflow,
    ProjectAgentWorkflowInput,
    ProjectAgentWorkflowStatus,
    ProjectChatRequest,
    ProjectChatResult,
    get_project_agent_workflow_id,
)

__all__ = [
    # Episode workflows
    "EpisodeProcessingWorkflow",
    "IncrementalRefreshWorkflow",
    # Entity workflows
    "DeduplicateEntitiesWorkflow",
    # Community workflows
    "RebuildCommunitiesWorkflow",
    # Agent workflows
    "AgentExecutionWorkflow",
    "AgentInput",
    "AgentState",
    # Agent Session workflows
    "AgentSessionWorkflow",
    "AgentSessionConfig",
    "AgentChatRequest",
    "AgentChatResult",
    "AgentSessionStatus",
    "get_agent_session_workflow_id",
    # Project Agent workflows (new)
    "ProjectAgentWorkflow",
    "ProjectAgentWorkflowInput",
    "ProjectAgentWorkflowStatus",
    "ProjectAgentMetrics",
    "ProjectChatRequest",
    "ProjectChatResult",
    "get_project_agent_workflow_id",
]
