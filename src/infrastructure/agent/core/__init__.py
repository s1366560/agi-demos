"""ReAct agent core package with lazy compatibility exports.

Core submodules import one another while the processor graph is assembled.
Avoid loading that graph merely because a leaf module such as ``llm_stream``
was imported.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins.business.agent.engine.react.project_react_agent import (
        ProjectAgentConfig,
        ProjectAgentManager,
        ProjectAgentMetrics,
        ProjectAgentStatus,
        ProjectReActAgent,
    )
    from plugins.business.agent.engine.react.react_agent import ReActAgent, create_react_agent

    from .processor import ProcessorConfig, SessionProcessor, ToolDefinition

_EXPORTS = {
    "ProcessorConfig": (".processor", "ProcessorConfig"),
    "SessionProcessor": (".processor", "SessionProcessor"),
    "ToolDefinition": (".processor", "ToolDefinition"),
    "ProjectAgentConfig": ("plugins.business.agent.engine.react.project_react_agent", "ProjectAgentConfig"),
    "ProjectAgentManager": ("plugins.business.agent.engine.react.project_react_agent", "ProjectAgentManager"),
    "ProjectAgentMetrics": ("plugins.business.agent.engine.react.project_react_agent", "ProjectAgentMetrics"),
    "ProjectAgentStatus": ("plugins.business.agent.engine.react.project_react_agent", "ProjectAgentStatus"),
    "ProjectReActAgent": ("plugins.business.agent.engine.react.project_react_agent", "ProjectReActAgent"),
    "ReActAgent": ("plugins.business.agent.engine.react.react_agent", "ReActAgent"),
    "create_react_agent": ("plugins.business.agent.engine.react.react_agent", "create_react_agent"),
}

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
]


def __getattr__(name: str) -> object:
    """Resolve historical package exports without eager graph construction."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    return getattr(import_module(module_name, __name__), attribute_name)
