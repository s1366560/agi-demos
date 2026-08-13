"""Compatibility import for retired SQL Workspace Collaboration authority."""

from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired


class LegacyWorkspaceCollaborationAuthorityRepository:
    """Reject all construction after Avernet became the sole Workspace authority."""

    def __init__(self, _session: object) -> None:
        legacy_workspace_runtime_retired("Collaboration authority repository")


__all__ = ["LegacyWorkspaceCollaborationAuthorityRepository"]
