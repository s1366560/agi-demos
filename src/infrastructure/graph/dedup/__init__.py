"""Deduplication strategies for graph nodes.

This module provides various deduplication strategies:
- HashDeduplicator: Exact duplicate detection using SHA256 hashes
"""

from src.infrastructure.graph.dedup.hash_deduplicator import HashDeduplicator

__all__ = ["HashDeduplicator"]
