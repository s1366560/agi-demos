from enum import Enum


class WorkspaceRole(str, Enum):
    """Workspace member role."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
