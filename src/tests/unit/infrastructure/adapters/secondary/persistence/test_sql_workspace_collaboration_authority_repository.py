"""Persistence tests for durable Workspace Collaboration mutation authority."""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_collaboration_authority import (
    WorkspaceCollaborationActor,
    WorkspaceCollaborationIdempotencyConflictError,
    WorkspaceCollaborationMutationCommand,
    WorkspaceCollaborationMutationService,
    WorkspaceCollaborationRevisionConflictError,
    WorkspaceCollaborationTargetNotFoundError,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    WorkspaceMemberModel,
    WorkspaceModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_collaboration_authority_repository import (
    SqlWorkspaceCollaborationAuthorityRepository,
)


async def _seed_workspace(db: AsyncSession) -> WorkspaceCollaborationActor:
    user = User(
        id="workspace-authority-user",
        email="workspace-authority@example.com",
        hashed_password="unused",
        is_active=True,
    )
    tenant = Tenant(
        id="workspace-authority-tenant",
        name="Workspace Authority",
        slug="workspace-authority",
        owner_id=user.id,
    )
    project = Project(
        id="workspace-authority-project",
        tenant_id=tenant.id,
        name="Workspace Authority",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
        is_public=False,
    )
    workspace = WorkspaceModel(
        id="workspace-authority-workspace",
        tenant_id=tenant.id,
        project_id=project.id,
        name="Workspace Authority",
        created_by=user.id,
        metadata_json={},
        hex_layout_config_json={},
        default_blocking_categories_json=[],
    )
    member = WorkspaceMemberModel(
        id="workspace-authority-member",
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
    )
    db.add_all([user, tenant, project, workspace, member])
    await db.flush()
    return WorkspaceCollaborationActor(
        tenant_id=tenant.id,
        project_id=project.id,
        workspace_id=workspace.id,
        user_id=user.id,
    )


def _command(
    *,
    key: str = "workspace-command-0001",
    expected_revision: int = 0,
    title: str = "Decision",
) -> WorkspaceCollaborationMutationCommand:
    return WorkspaceCollaborationMutationCommand(
        contract_version="2.0.0",
        surface="discussion",
        action="create_post",
        expected_revision=expected_revision,
        idempotency_key=key,
        payload={"title": title, "content": "Ship it"},
    )


@pytest.mark.unit
async def test_workspace_authority_reserves_finalizes_and_replays(
    db_session: AsyncSession,
) -> None:
    actor = await _seed_workspace(db_session)
    service = WorkspaceCollaborationMutationService(
        SqlWorkspaceCollaborationAuthorityRepository(db_session)
    )
    command = _command()

    assert await service.current_revision(actor=actor) == 0
    reserved = await service.reserve(actor=actor, command=command)
    assert reserved.dispatch_required is True
    assert reserved.revision is None

    finalized = await service.finalize(
        actor=actor,
        command=command,
        duplicate=False,
    )
    assert finalized.revision == 1
    assert finalized.duplicate is False
    assert await service.current_revision(actor=actor) == 1

    replay = await service.reserve(actor=actor, command=command)
    assert replay.dispatch_required is False
    assert replay.duplicate is True
    assert replay.revision == 1


@pytest.mark.unit
async def test_workspace_authority_fails_closed_for_revision_idempotency_and_scope(
    db_session: AsyncSession,
) -> None:
    actor = await _seed_workspace(db_session)
    service = WorkspaceCollaborationMutationService(
        SqlWorkspaceCollaborationAuthorityRepository(db_session)
    )
    command = _command()
    await service.reserve(actor=actor, command=command)
    await service.finalize(actor=actor, command=command, duplicate=False)

    with pytest.raises(WorkspaceCollaborationIdempotencyConflictError):
        await service.reserve(actor=actor, command=_command(title="Different"))

    with pytest.raises(WorkspaceCollaborationRevisionConflictError) as stale:
        await service.reserve(
            actor=actor,
            command=_command(key="workspace-command-0002", expected_revision=0),
        )
    assert stale.value.current_revision == 1

    with pytest.raises(WorkspaceCollaborationTargetNotFoundError):
        await service.current_revision(
            actor=WorkspaceCollaborationActor(
                tenant_id=actor.tenant_id,
                project_id="other-project",
                workspace_id=actor.workspace_id,
                user_id=actor.user_id,
            )
        )


@pytest.mark.unit
def test_workspace_authority_initialization_is_postgresql_upsert() -> None:
    actor = WorkspaceCollaborationActor(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
    )

    statement = SqlWorkspaceCollaborationAuthorityRepository._authority_insert_statement(
        actor=actor,
        dialect_name="postgresql",
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "ON CONFLICT (workspace_id) DO NOTHING" in sql
    assert "'workspace-1'" in sql
    assert "'tenant-1'" in sql
    assert "'project-1'" in sql
