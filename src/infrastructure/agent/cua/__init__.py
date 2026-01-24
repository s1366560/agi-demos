"""
CUA (Computer Use Agent) Integration Module.

This module provides integration between MemStack's ReActAgent and CUA framework,
enabling computer control capabilities through a three-layer architecture:

- L1 (Tool Layer): CUA operations as MemStack AgentTools
- L2 (Skill Layer): CUA tasks as predefined Skills
- L3 (SubAgent Layer): CUA ComputerAgent as MemStack SubAgent

Key Components:
- CUAAdapter: Core bridge between CUA and MemStack
- CUAToolAdapter: Base class for CUA tool wrappers
- CUASkillManager: Manages CUA-related skills
- CUASubAgent: CUA ComputerAgent as SubAgent

Usage:
    from src.infrastructure.agent.cua import CUAAdapter, CUAConfig

    config = CUAConfig()
    adapter = CUAAdapter(config)
    tools = adapter.create_tools()
"""

from .adapter import CUAAdapter
from .config import CUAConfig

__all__ = [
    "CUAAdapter",
    "CUAConfig",
]
