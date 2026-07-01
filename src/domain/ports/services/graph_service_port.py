"""DEPRECATED: use ``GraphStorePort`` instead.

This module is kept only for backward compatibility during the pluggable graph
backend migration. ``GraphServicePort`` is now an alias for ``GraphStorePort``,
which is a strict superset (it retains all six original methods plus the new
semantic store primitives). Existing imports and type annotations keep working
unchanged.

This file will be removed once all call sites have migrated to ``GraphStorePort``
(Phase 2 of the graph backend refactor). Do not add new references to
``GraphServicePort``.
"""

from __future__ import annotations

from src.domain.ports.services.graph_store_port import GraphStorePort

# Deprecation alias. GraphStorePort carries every method GraphServicePort did,
# so any value typed as GraphServicePort continues to satisfy the contract.
GraphServicePort = GraphStorePort

__all__ = ["GraphServicePort"]
