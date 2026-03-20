"""
Cache adapters for repository caching.

This module provides cached implementations of repositories using Redis
to improve performance for frequently accessed data.
"""

from src.infrastructure.adapters.secondary.cache.cached_workflow_pattern_repository import (
    CachedWorkflowPatternRepository,
)
from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
    RedisAgentCredentialScopeAdapter,
)
from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
    RedisAgentNamespaceAdapter,
)

__all__ = [
    "CachedWorkflowPatternRepository",
    "RedisAgentCredentialScopeAdapter",
    "RedisAgentNamespaceAdapter",
]
