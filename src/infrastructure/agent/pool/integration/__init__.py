"""
Pool Integration Module.

提供新池化架构与现有系统的集成适配器。
"""

from .session_adapter import PooledAgentSessionAdapter

__all__ = [
    "PooledAgentSessionAdapter",
]
