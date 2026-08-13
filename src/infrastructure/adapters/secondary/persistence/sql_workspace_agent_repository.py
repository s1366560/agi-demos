"""Compatibility import for the retired SQL Workspace agent repository."""

from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired


class LegacyWorkspaceAgentRepository:
    """Reject all construction after Avernet became the sole Workspace authority."""

    def __init__(self, _session: object) -> None:
        legacy_workspace_runtime_retired("agent repository")


__all__ = ["LegacyWorkspaceAgentRepository"]
