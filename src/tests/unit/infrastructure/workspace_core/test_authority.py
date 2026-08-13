"""Tests for the Avernet-backed canonical Workspace authority adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityAccessDeniedError,
    WorkspaceAuthorityScope,
    WorkspaceAuthorityUnavailableError,
)
from src.infrastructure.workspace_core.authority import AvernetWorkspaceAuthority
from src.infrastructure.workspace_core.client import (
    WorkspaceAuthorityQueryProfile,
    WorkspaceAuthorityQueryResponse,
    WorkspaceAuthorityTaskLink,
    WorkspaceCoreAgent,
    WorkspaceCoreClient,
    WorkspaceCoreClientError,
)


def _profile(
    workspace_id: str,
    *,
    project_id: str = "project-1",
    archived: bool = False,
) -> WorkspaceAuthorityQueryProfile:
    return WorkspaceAuthorityQueryProfile(
        workspace_id=workspace_id,
        tenant_id="tenant-1",
        project_id=project_id,
        name=f"Workspace {workspace_id}",
        created_by="owner-1",
        is_archived=archived,
        metadata={"source": "core"},
        member_role="editor",
    )


def _authority(result: WorkspaceAuthorityQueryResponse) -> tuple[AvernetWorkspaceAuthority, AsyncMock]:
    client = MagicMock(spec=WorkspaceCoreClient)
    query = AsyncMock(return_value=result)
    client.query_workspace_authority = query
    return AvernetWorkspaceAuthority(client), query


@pytest.mark.unit
async def test_accessible_profiles_batches_filters_and_scope_checks() -> None:
    authority, query = _authority(
        WorkspaceAuthorityQueryResponse(
            profiles=[
                _profile("workspace-live"),
                _profile("workspace-archived", archived=True),
                _profile("workspace-cross-project", project_id="project-2"),
            ],
            task_links=[],
        )
    )

    profiles = await authority.accessible_profiles(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_ids={"workspace-live", "workspace-archived", "workspace-cross-project"},
        user_id="user-1",
    )

    assert set(profiles) == {"workspace-live"}
    request = query.await_args.args[0]
    assert request.workspace_ids == [
        "workspace-archived",
        "workspace-cross-project",
        "workspace-live",
    ]
    assert request.actor.user_id == "user-1"
    assert request.task_refs == []


@pytest.mark.unit
async def test_resolve_profiles_preserves_member_role_and_fails_closed_for_non_members() -> None:
    authority, _query = _authority(
        WorkspaceAuthorityQueryResponse(
            profiles=[
                _profile("workspace-member"),
                _profile("workspace-no-member").model_copy(update={"member_role": None}),
                _profile("workspace-archived", archived=True),
            ],
            task_links=[],
        )
    )

    profiles = await authority.resolve_profiles(
        workspace_ids={"workspace-member", "workspace-no-member", "workspace-archived"},
        user_id="user-1",
    )

    assert set(profiles) == {"workspace-member"}
    assert profiles["workspace-member"].member_role == "editor"


@pytest.mark.unit
async def test_resolve_profiles_allows_superuser_without_synthesizing_member_role() -> None:
    authority, _query = _authority(
        WorkspaceAuthorityQueryResponse(
            profiles=[_profile("workspace-1").model_copy(update={"member_role": None})],
            task_links=[],
        )
    )

    profiles = await authority.resolve_profiles(
        workspace_ids={"workspace-1"},
        user_id="admin-1",
        is_superuser=True,
    )

    assert profiles["workspace-1"].member_role is None


@pytest.mark.unit
async def test_resolve_profiles_maps_core_failure_to_unavailable() -> None:
    client = MagicMock(spec=WorkspaceCoreClient)
    client.query_workspace_authority = AsyncMock(side_effect=WorkspaceCoreClientError("offline"))
    authority = AvernetWorkspaceAuthority(client)

    with pytest.raises(WorkspaceAuthorityUnavailableError):
        await authority.resolve_profiles(workspace_ids={"workspace-1"}, user_id="user-1")


@pytest.mark.unit
async def test_has_task_uses_batched_profile_and_task_link_contract() -> None:
    authority, query = _authority(
        WorkspaceAuthorityQueryResponse(
            profiles=[_profile("workspace-1")],
            task_links=[
                WorkspaceAuthorityTaskLink(
                    workspace_id="workspace-1",
                    task_id="task-1",
                    linked=True,
                )
            ],
        )
    )

    linked = await authority.has_task(
        WorkspaceAuthorityScope(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            user_id="user-1",
        ),
        "task-1",
    )

    assert linked is True
    request = query.await_args.args[0]
    assert request.workspace_ids == ["workspace-1"]
    assert request.task_refs[0].workspace_id == "workspace-1"
    assert request.task_refs[0].task_id == "task-1"


@pytest.mark.unit
async def test_has_task_fails_closed_when_profile_is_omitted() -> None:
    authority, _query = _authority(
        WorkspaceAuthorityQueryResponse(
            profiles=[],
            task_links=[
                WorkspaceAuthorityTaskLink(
                    workspace_id="workspace-1",
                    task_id="task-1",
                    linked=False,
                )
            ],
        )
    )

    with pytest.raises(WorkspaceAuthorityAccessDeniedError):
        await authority.has_task(
            WorkspaceAuthorityScope(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                user_id="outsider",
            ),
            "task-1",
        )


@pytest.mark.unit
async def test_list_agents_preserves_canonical_binding_projection() -> None:
    client = MagicMock(spec=WorkspaceCoreClient)
    client.list_workspace_agents = AsyncMock(
        return_value=[
            WorkspaceCoreAgent(
                id="binding-1",
                workspace_id="workspace-1",
                agent_id="agent-1",
                display_name="Worker",
                label="worker",
                status="busy",
                is_active=True,
            )
        ]
    )
    authority = AvernetWorkspaceAuthority(client)

    agents = await authority.list_agents(
        WorkspaceAuthorityScope(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            user_id="user-1",
        )
    )

    assert agents[0].binding_id == "binding-1"
    assert agents[0].agent_id == "agent-1"
