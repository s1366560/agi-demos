"""Workspace authority adapter backed exclusively by Avernet Workspace Core."""

from __future__ import annotations

from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityAccessDeniedError,
    WorkspaceAuthorityAgent,
    WorkspaceAuthorityNotFoundError,
    WorkspaceAuthorityPort,
    WorkspaceAuthorityProfile,
    WorkspaceAuthorityResolvedProfile,
    WorkspaceAuthorityScope,
    WorkspaceAuthorityUnavailableError,
)
from src.infrastructure.workspace_core.client import (
    WorkspaceAuthorityActor,
    WorkspaceAuthorityQueryRequest,
    WorkspaceAuthorityTaskRef,
    WorkspaceCoreClient,
    WorkspaceCoreClientError,
    WorkspaceCoreForbiddenError,
    WorkspaceCoreNotFoundError,
)


class AvernetWorkspaceAuthority(WorkspaceAuthorityPort):
    def __init__(self, client: WorkspaceCoreClient) -> None:
        super().__init__()
        self._client = client

    async def get_profile(self, scope: WorkspaceAuthorityScope) -> WorkspaceAuthorityProfile:
        try:
            profile = await self._client.read_workspace_profile(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                workspace_id=scope.workspace_id,
                user_id=scope.user_id,
                is_superuser=scope.is_superuser,
            )
        except WorkspaceCoreNotFoundError as exc:
            raise WorkspaceAuthorityNotFoundError from exc
        except WorkspaceCoreForbiddenError as exc:
            raise WorkspaceAuthorityAccessDeniedError from exc
        except WorkspaceCoreClientError as exc:
            raise WorkspaceAuthorityUnavailableError from exc
        return WorkspaceAuthorityProfile(
            workspace_id=profile.id,
            tenant_id=profile.tenant_id,
            project_id=profile.project_id,
            name=profile.name,
            created_by=profile.created_by,
            is_archived=profile.is_archived,
            metadata=profile.metadata,
        )

    async def get_membership_role(self, scope: WorkspaceAuthorityScope) -> str:
        _ = await self.get_profile(scope)
        if scope.is_superuser:
            return "owner"
        try:
            members = await self._client.list_workspace_members(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                workspace_id=scope.workspace_id,
                user_id=scope.user_id,
                is_superuser=scope.is_superuser,
            )
        except WorkspaceCoreForbiddenError as exc:
            raise WorkspaceAuthorityAccessDeniedError from exc
        except WorkspaceCoreNotFoundError as exc:
            raise WorkspaceAuthorityNotFoundError from exc
        except WorkspaceCoreClientError as exc:
            raise WorkspaceAuthorityUnavailableError from exc
        member = next((item for item in members if item.user_id == scope.user_id), None)
        if member is None:
            raise WorkspaceAuthorityAccessDeniedError
        return member.role

    async def has_task(self, scope: WorkspaceAuthorityScope, task_id: str) -> bool:
        try:
            result = await self._client.query_workspace_authority(
                WorkspaceAuthorityQueryRequest(
                    actor=WorkspaceAuthorityActor(
                        user_id=scope.user_id,
                        is_superuser=scope.is_superuser,
                    ),
                    workspace_ids=[scope.workspace_id],
                    task_refs=[
                        WorkspaceAuthorityTaskRef(
                            workspace_id=scope.workspace_id,
                            task_id=task_id,
                        )
                    ],
                )
            )
        except WorkspaceCoreForbiddenError as exc:
            raise WorkspaceAuthorityAccessDeniedError from exc
        except (WorkspaceCoreNotFoundError, WorkspaceCoreClientError) as exc:
            raise WorkspaceAuthorityUnavailableError from exc
        profile = next(
            (
                item
                for item in result.profiles
                if item.workspace_id == scope.workspace_id
                and item.tenant_id == scope.tenant_id
                and item.project_id == scope.project_id
            ),
            None,
        )
        if profile is None:
            raise WorkspaceAuthorityAccessDeniedError
        return any(
            link.workspace_id == scope.workspace_id
            and link.task_id == task_id
            and link.linked
            for link in result.task_links
        )

    async def list_agents(
        self,
        scope: WorkspaceAuthorityScope,
        *,
        active_only: bool = True,
    ) -> tuple[WorkspaceAuthorityAgent, ...]:
        try:
            agents = await self._client.list_workspace_agents(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                workspace_id=scope.workspace_id,
                user_id=scope.user_id,
                is_superuser=scope.is_superuser,
                active_only=active_only,
            )
        except WorkspaceCoreForbiddenError as exc:
            raise WorkspaceAuthorityAccessDeniedError from exc
        except WorkspaceCoreNotFoundError as exc:
            raise WorkspaceAuthorityNotFoundError from exc
        except WorkspaceCoreClientError as exc:
            raise WorkspaceAuthorityUnavailableError from exc
        return tuple(
            WorkspaceAuthorityAgent(
                binding_id=agent.id,
                workspace_id=agent.workspace_id,
                agent_id=agent.agent_id,
                display_name=agent.display_name,
                label=agent.label,
                status=agent.status,
                is_active=agent.is_active,
            )
            for agent in agents
            if agent.workspace_id == scope.workspace_id
        )

    async def accessible_profiles(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_ids: set[str],
        user_id: str,
        is_superuser: bool = False,
    ) -> dict[str, WorkspaceAuthorityProfile]:
        profiles = await self.resolve_profiles(
            workspace_ids=workspace_ids,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        return {
            workspace_id: profile
            for workspace_id, profile in profiles.items()
            if profile.tenant_id == tenant_id
            and profile.project_id == project_id
        }

    async def resolve_profiles(
        self,
        *,
        workspace_ids: set[str],
        user_id: str,
        is_superuser: bool = False,
    ) -> dict[str, WorkspaceAuthorityResolvedProfile]:
        if not workspace_ids:
            return {}
        try:
            result = await self._client.query_workspace_authority(
                WorkspaceAuthorityQueryRequest(
                    actor=WorkspaceAuthorityActor(
                        user_id=user_id,
                        is_superuser=is_superuser,
                    ),
                    workspace_ids=sorted(workspace_ids),
                )
            )
        except (WorkspaceCoreForbiddenError, WorkspaceCoreNotFoundError) as exc:
            raise WorkspaceAuthorityAccessDeniedError from exc
        except WorkspaceCoreClientError as exc:
            raise WorkspaceAuthorityUnavailableError from exc
        return {
            profile.workspace_id: WorkspaceAuthorityResolvedProfile(
                workspace_id=profile.workspace_id,
                tenant_id=profile.tenant_id,
                project_id=profile.project_id,
                name=profile.name,
                created_by=profile.created_by,
                is_archived=profile.is_archived,
                metadata=profile.metadata,
                member_role=profile.member_role,
            )
            for profile in result.profiles
            if profile.workspace_id in workspace_ids
            and not profile.is_archived
            and (is_superuser or profile.member_role is not None)
        }
