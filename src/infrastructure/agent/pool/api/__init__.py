"""
Pool API Module.

提供池状态查询和管理的 REST API。
"""

from .router import create_pool_router

__all__ = [
    "create_pool_router",
]
