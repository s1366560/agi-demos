"""Canonical Workspace authority read port for platform-owned integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, kw_only=True)
class WorkspaceAuthorityScope:
    tenant_id: str
    project_id: str
    workspace_id: str
    user_id: str
    is_superuser: bool = False


@dataclass(frozen=True, kw_only=True)
class WorkspaceAuthorityProfile:
    workspace_id: str
    tenant_id: str
    project_id: str
    name: str
    created_by: str
    is_archived: bool
    metadata: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class WorkspaceAuthorityResolvedProfile(WorkspaceAuthorityProfile):
    member_role: str | None


@dataclass(frozen=True, kw_only=True)
class WorkspaceAuthorityAgent:
    binding_id: str
    workspace_id: str
    agent_id: str
    display_name: str | None
    label: str | None
    status: str
    is_active: bool


class WorkspaceAuthorityNotFoundError(Exception):
    """The requested canonical Workspace resource does not exist in the scope."""


class WorkspaceAuthorityAccessDeniedError(Exception):
    """The caller is not a current canonical Workspace member."""


class WorkspaceAuthorityUnavailableError(Exception):
    """The canonical Workspace authority cannot answer safely."""


class WorkspaceAuthorityPort(Protocol):
    async def get_profile(self, scope: WorkspaceAuthorityScope) -> WorkspaceAuthorityProfile: ...

    async def get_membership_role(self, scope: WorkspaceAuthorityScope) -> str: ...

    async def has_task(self, scope: WorkspaceAuthorityScope, task_id: str) -> bool: ...

    async def list_agents(
        self,
        scope: WorkspaceAuthorityScope,
        *,
        active_only: bool = True,
    ) -> tuple[WorkspaceAuthorityAgent, ...]: ...

    async def resolve_profiles(
        self,
        *,
        workspace_ids: set[str],
        user_id: str,
        is_superuser: bool = False,
    ) -> dict[str, WorkspaceAuthorityResolvedProfile]: ...

    async def accessible_profiles(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_ids: set[str],
        user_id: str,
        is_superuser: bool = False,
    ) -> dict[str, WorkspaceAuthorityProfile]: ...
