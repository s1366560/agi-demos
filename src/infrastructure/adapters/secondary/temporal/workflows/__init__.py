"""
Temporal Workflows for MemStack.

This module provides Temporal workflow definitions for:
- Episode processing
- Entity deduplication
- Community rebuilding
- Project-level agent sessions
"""

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
    # Project Agent workflows (primary agent interface)
    "ProjectAgentWorkflow",
    "ProjectAgentWorkflowInput",
    "ProjectAgentWorkflowStatus",
    "ProjectAgentMetrics",
    "ProjectChatRequest",
    "ProjectChatResult",
    "get_project_agent_workflow_id",
]
