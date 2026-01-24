"""Doom Loop detection module.

Detects when the agent gets stuck in a loop of repeated tool calls.
"""

from .detector import DoomLoopDetector, ToolCallRecord

__all__ = ["DoomLoopDetector", "ToolCallRecord"]
