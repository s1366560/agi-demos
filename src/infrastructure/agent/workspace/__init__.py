"""Workspace file loading for agent persona/soul/identity system.

Loads bootstrap files from .memstack/workspace/ directory in the sandbox.
Inspired by OpenClaw's workspace.ts bootstrap system.
"""

from src.infrastructure.agent.workspace.manager import WorkspaceFiles, WorkspaceManager

__all__ = ["WorkspaceFiles", "WorkspaceManager"]
