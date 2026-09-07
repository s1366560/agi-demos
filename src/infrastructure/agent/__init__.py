"""Agent infrastructure package with lazy compatibility exports.

Importing any agent submodule executes this package initializer.  Keep it free
of eager imports so lower-level modules can be used without constructing the
entire ReAct dependency graph.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.agent.core.react_agent import ReActAgent
    from src.infrastructure.agent.tools.base import AgentTool

__all__ = [
    "AgentTool",
    "ReActAgent",
]


def __getattr__(name: str) -> object:
    """Resolve the historical package exports without eager imports."""
    if name == "ReActAgent":
        from src.infrastructure.agent.core.react_agent import ReActAgent

        return ReActAgent
    if name == "AgentTool":
        from src.infrastructure.agent.tools.base import AgentTool

        return AgentTool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
