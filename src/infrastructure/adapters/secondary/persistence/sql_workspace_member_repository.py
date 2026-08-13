"""Compatibility import for the retired SQL Workspace member repository."""

from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired


class LegacyWorkspaceMemberRepository:
    """Reject all construction after Avernet became the sole Workspace authority."""

    def __init__(self, _session: object) -> None:
        legacy_workspace_runtime_retired("member repository")


__all__ = ["LegacyWorkspaceMemberRepository"]
