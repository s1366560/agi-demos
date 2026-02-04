"""
Agent Pool 后端模块.

Provides tier-specific backends:
- SharedPoolBackend: WARM tier, shared worker pool with LRU
- OnDemandBackend: COLD tier, on-demand creation
- ContainerBackend: HOT tier, dedicated containers (Docker/K8s)
"""

from .base import Backend, BackendType
from .shared_pool_backend import SharedPoolBackend
from .ondemand_backend import OnDemandBackend
from .container_backend import ContainerBackend

__all__ = [
    "Backend",
    "BackendType",
    "SharedPoolBackend",
    "OnDemandBackend",
    "ContainerBackend",
]
