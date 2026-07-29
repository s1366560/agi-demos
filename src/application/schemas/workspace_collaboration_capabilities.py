"""Versioned Workspace Collaboration capability contract."""

from typing import Final, Literal, cast

from pydantic import BaseModel, ConfigDict

from src.application.services.workspace_collaboration_authority import (
    WORKSPACE_COLLABORATION_CONTRACT_VERSION,
    WORKSPACE_COLLABORATION_MUTATION_ACTIONS,
)

WORKSPACE_COLLABORATION_SERVICE_VERSION: Final[Literal["0.2.0"]] = "0.2.0"

WorkspaceCollaborationSurface = Literal[
    "goals",
    "discussion",
    "status",
    "collaboration",
    "members",
    "genes",
    "files",
    "notes",
    "topology",
    "settings",
]

WORKSPACE_COLLABORATION_READ_SURFACES: tuple[WorkspaceCollaborationSurface, ...] = (
    "goals",
    "discussion",
    "status",
    "collaboration",
    "members",
    "genes",
    "files",
    "notes",
    "topology",
    "settings",
)


class WorkspaceCollaborationMutationCapability(BaseModel):
    """Durable mutation guarantees for all declared surface actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: Literal[True] = True
    revision_guarded: Literal[True] = True
    idempotency_guarded: Literal[True] = True
    actions: dict[WorkspaceCollaborationSurface, list[str]]


class WorkspaceCollaborationCapabilitiesResponse(BaseModel):
    """Cloud capability declaration for one tenant/project/workspace scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service_version: Literal["0.2.0"] = WORKSPACE_COLLABORATION_SERVICE_VERSION
    contract_version: Literal["2.0.0"] = WORKSPACE_COLLABORATION_CONTRACT_VERSION
    authority: Literal["cloud"] = "cloud"
    tenant_id: str
    project_id: str
    workspace_id: str
    status: Literal["available"] = "available"
    reason_code: None = None
    canonical_read: Literal[True] = True
    read_surfaces: list[WorkspaceCollaborationSurface]
    mutations: WorkspaceCollaborationMutationCapability
    allowed_actions: dict[WorkspaceCollaborationSurface, list[str]]


def build_workspace_collaboration_capabilities(
    *,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    mutation_actions: dict[WorkspaceCollaborationSurface, list[str]] | None = None,
) -> WorkspaceCollaborationCapabilitiesResponse:
    """Build the immutable read and mutation authority declaration for one scope."""
    actions = cast(
        dict[WorkspaceCollaborationSurface, list[str]],
        {
            surface: list(WORKSPACE_COLLABORATION_MUTATION_ACTIONS[surface])
            for surface in WORKSPACE_COLLABORATION_READ_SURFACES
        }
        if mutation_actions is None
        else mutation_actions
    )
    return WorkspaceCollaborationCapabilitiesResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_id=workspace_id,
        read_surfaces=list(WORKSPACE_COLLABORATION_READ_SURFACES),
        mutations=WorkspaceCollaborationMutationCapability(actions=actions),
        allowed_actions=actions,
    )
