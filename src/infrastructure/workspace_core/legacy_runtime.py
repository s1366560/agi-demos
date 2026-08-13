"""Fail-closed boundary for platform-owned legacy Workspace persistence."""

from __future__ import annotations

from typing import Never


class LegacyWorkspaceRuntimeRetiredError(RuntimeError):
    """Raised when a removed SQL Workspace runtime path is invoked."""


def legacy_workspace_runtime_retired(capability: str) -> Never:
    """Reject a legacy Workspace capability without touching platform SQL tables."""
    raise LegacyWorkspaceRuntimeRetiredError(
        f"Platform SQL Workspace {capability} is retired; use Avernet Workspace Core"
    )


__all__ = [
    "LegacyWorkspaceRuntimeRetiredError",
    "legacy_workspace_runtime_retired",
]
