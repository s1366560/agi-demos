"""Dependency type enum for enhanced task DAG edges."""

from __future__ import annotations

from enum import Enum


class DependencyType(str, Enum):
    """Type of dependency between tasks in a SubAgent DAG.

    HARD: child cannot start until parent completes.
    SOFT: child may start but should prefer waiting for parent.
    STREAMING: child receives incremental results from parent.
    """

    HARD = "hard"
    SOFT = "soft"
    STREAMING = "streaming"
