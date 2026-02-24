"""Agent tools for ReAct agent.

This module contains the tool definitions used by the ReAct agent
to interact with the knowledge graph and memory systems.
"""

from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.clarification import ClarificationTool
from src.infrastructure.agent.tools.decision import DecisionTool
from src.infrastructure.agent.tools.desktop_tool import DesktopStatus, DesktopTool
from src.infrastructure.agent.tools.env_var_tools import (
    CheckEnvVarsTool,
    GetEnvVarTool,
    RequestEnvVarTool,
)
from src.infrastructure.agent.tools.plugin_manager import PluginManagerTool
from src.infrastructure.agent.tools.sandbox_tool_wrapper import SandboxMCPToolWrapper
from src.infrastructure.agent.tools.skill_installer import SkillInstallerTool
from src.infrastructure.agent.tools.skill_loader import SkillLoaderTool
from src.infrastructure.agent.tools.subagent_sessions import (
    SessionsHistoryTool,
    SessionsListTool,
    SessionsSendTool,
    SessionsSpawnTool,
    SubAgentsControlTool,
)
from src.infrastructure.agent.tools.terminal_tool import TerminalStatus, TerminalTool
from src.infrastructure.agent.tools.todo_tools import (
    TodoReadTool,
    TodoWriteTool,
    create_todoread_tool,
    create_todowrite_tool,
)
from src.infrastructure.agent.tools.web_scrape import WebScrapeTool
from src.infrastructure.agent.tools.web_search import WebSearchTool

__all__ = [
    "AgentTool",
    # Environment Variable Tools
    "CheckEnvVarsTool",
    "ClarificationTool",
    "DecisionTool",
    "DesktopStatus",
    "DesktopTool",
    "GetEnvVarTool",
    "PluginManagerTool",
    "RequestEnvVarTool",
    "SandboxMCPToolWrapper",
    "SessionsHistoryTool",
    "SessionsListTool",
    "SessionsSendTool",
    "SessionsSpawnTool",
    "SkillInstallerTool",
    "SkillLoaderTool",
    "SubAgentsControlTool",
    "TerminalStatus",
    "TerminalTool",
    "TodoReadTool",
    "TodoWriteTool",
    "WebScrapeTool",
    "WebSearchTool",
    "create_todoread_tool",
    "create_todowrite_tool",
]
