"""
System Prompt Management Module.

This module provides a modular system for managing and assembling
system prompts for the ReAct Agent, supporting:
- Multi-model adaptation (Claude, Gemini, Qwen, etc.)
- Dynamic mode switching (Plan/Build)
- Environment context injection
- Custom rules loading (.memstack/AGENTS.md, CLAUDE.md)

Reference: OpenCode's system.ts and prompt management architecture.
"""

from .loader import PromptLoader
from .manager import ModelProvider, PromptContext, PromptMode, SystemPromptManager
from .persona import AgentPersona, PersonaField, PersonaSource, PromptReport, PromptSectionEntry
from .tool_summaries import apply_tool_summaries, sort_by_tool_order

__all__ = [
    "AgentPersona",
    "ModelProvider",
    "PersonaField",
    "PersonaSource",
    "PromptContext",
    "PromptLoader",
    "PromptMode",
    "PromptReport",
    "PromptSectionEntry",
    "SystemPromptManager",
    "apply_tool_summaries",
    "sort_by_tool_order",
]
