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

__all__ = [
    "ModelProvider",
    "PromptContext",
    "PromptLoader",
    "PromptMode",
    "SystemPromptManager",
]
