"""Versioned Workspace Collaboration capability contract."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

WORKSPACE_COLLABORATION_SERVICE_VERSION: Final[Literal["0.1.0"]] = "0.1.0"
WORKSPACE_COLLABORATION_CONTRACT_VERSION: Final[Literal["2.0.0"]] = "2.0.0"
WORKSPACE_COLLABORATION_DEGRADED_REASON: Final[
    Literal["workspace_collaboration_mutation_guards_unavailable"]
] = "workspace_collaboration_mutation_guards_unavailable"

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
    """Current mutation authority, kept explicit until guards are durable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: Literal[False] = False
    revision_guarded: Literal[False] = False
    idempotency_guarded: Literal[False] = False


class WorkspaceCollaborationCapabilitiesResponse(BaseModel):
    """Cloud capability declaration for one tenant/project/workspace scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service_version: Literal["0.1.0"] = WORKSPACE_COLLABORATION_SERVICE_VERSION
    contract_version: Literal["2.0.0"] = WORKSPACE_COLLABORATION_CONTRACT_VERSION
    authority: Literal["cloud"] = "cloud"
    tenant_id: str
    project_id: str
    workspace_id: str
    status: Literal["degraded"] = "degraded"
    reason_code: Literal["workspace_collaboration_mutation_guards_unavailable"] = (
        WORKSPACE_COLLABORATION_DEGRADED_REASON
    )
    canonical_read: Literal[True] = True
    read_surfaces: list[WorkspaceCollaborationSurface]
    mutations: WorkspaceCollaborationMutationCapability


def build_workspace_collaboration_capabilities(
    *,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
) -> WorkspaceCollaborationCapabilitiesResponse:
    """Build the immutable read-only authority declaration for one scope."""
    return WorkspaceCollaborationCapabilitiesResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_id=workspace_id,
        read_surfaces=list(WORKSPACE_COLLABORATION_READ_SURFACES),
        mutations=WorkspaceCollaborationMutationCapability(),
    )
