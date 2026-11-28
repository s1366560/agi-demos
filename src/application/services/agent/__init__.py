"""Agent service exports. Load business implementations only when requested."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.services.agent.conversation_manager import ConversationManager
    from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
    from src.application.services.agent.tool_discovery import ToolDiscoveryService

__all__ = ["AgentRuntimeBootstrapper", "ConversationManager", "ToolDiscoveryService"]

_MODULES = {
    "AgentRuntimeBootstrapper": "runtime_bootstrapper",
    "ConversationManager": "conversation_manager",
    "ToolDiscoveryService": "tool_discovery",
}


def __getattr__(name: str) -> object:
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(name)
    value: object = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value
