"""
Cache adapters for repository caching.

This module provides cached implementations of repositories using Redis
to improve performance for frequently accessed data.
"""

from src.infrastructure.adapters.secondary.cache.cached_workflow_pattern_repository import (
    CachedWorkflowPatternRepository,
)

__all__ = ["CachedWorkflowPatternRepository"]
