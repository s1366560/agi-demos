"""Permission matrix for workspace operations."""

from src.domain.model.workspace.workspace_role import WorkspaceRole

WORKSPACE_PERMISSION_MATRIX: dict[WorkspaceRole, frozenset[str]] = {
    WorkspaceRole.OWNER: frozenset(
        {
            "manage_agents",
            "move_agents",
            "manage_tasks",
            "manage_objectives",
            "manage_genes",
            "manage_blackboard",
            "manage_topology",
            "manage_members",
            "view_workspace",
        }
    ),
    WorkspaceRole.EDITOR: frozenset(
        {
            "move_agents",
            "manage_tasks",
            "manage_objectives",
            "manage_genes",
            "manage_blackboard",
            "view_workspace",
        }
    ),
    WorkspaceRole.VIEWER: frozenset(
        {
            "view_workspace",
        }
    ),
}


def has_permission(role: WorkspaceRole, action: str) -> bool:
    """Check if a role has permission for an action."""
    allowed = WORKSPACE_PERMISSION_MATRIX.get(role)
    if allowed is None:
        return False
    return action in allowed


def get_allowed_actions(role: WorkspaceRole) -> frozenset[str]:
    """Get all allowed actions for a role."""
    return WORKSPACE_PERMISSION_MATRIX.get(role, frozenset())
