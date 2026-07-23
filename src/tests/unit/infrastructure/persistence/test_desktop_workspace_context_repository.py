"""Contract tests for the authoritative desktop workspace context repository."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.workspace_context import (
    WorkspaceContextError,
    WorkspaceContextErrorCode,
    WorkspaceContextSwitchRequest,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_desktop_workspace_context_repository import (
    SqlDesktopWorkspaceContextRepository,
)


async def _seed_accessible_projects(db: AsyncSession) -> tuple[User, Tenant, Project, Project]:
    user = User(
        id="desktop-context-user",
        email="desktop-context@example.com",
        hashed_password="unused",
        full_name="Desktop Context User",
        is_active=True,
    )
    tenant = Tenant(
        id="desktop-context-tenant",
        name="Desktop Context Tenant",
        slug="desktop-context-tenant",
        owner_id=user.id,
    )
    default_project = Project(
        id="desktop-context-default-project",
        tenant_id=tenant.id,
        name="Default project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
        is_public=False,
    )
    other_project = Project(
        id="desktop-context-other-project",
        tenant_id=tenant.id,
        name="Other project",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
        is_public=False,
    )
    db.add_all(
        [
            user,
            tenant,
            default_project,
            other_project,
            UserTenant(
                id="desktop-context-membership",
                user_id=user.id,
                tenant_id=tenant.id,
                role="admin",
                permissions={},
            ),
            UserProject(
                id="desktop-context-default-access",
                user_id=user.id,
                project_id=default_project.id,
                role="owner",
                permissions={},
            ),
            UserProject(
                id="desktop-context-other-access",
                user_id=user.id,
                project_id=other_project.id,
                role="member",
                permissions={},
            ),
        ]
    )
    await db.flush()
    return user, tenant, default_project, other_project


@pytest.mark.unit
async def test_workspace_context_initializes_default_and_switches_idempotently(
    db_session: AsyncSession,
) -> None:
    user, tenant, default_project, other_project = await _seed_accessible_projects(db_session)
    repository = SqlDesktopWorkspaceContextRepository(db_session)
    observed_at = datetime.now(UTC)

    initial = await repository.get_or_initialize(user.id, observed_at)

    assert initial.context.tenant_id == tenant.id
    assert initial.context.project_id == default_project.id
    assert initial.context.revision == 0
    assert initial.membership_role == "admin"

    request = WorkspaceContextSwitchRequest(
        tenant_id=tenant.id,
        project_id=other_project.id,
        expected_revision=0,
        idempotency_key="desktop-context-switch-1",
    )
    switched = await repository.switch(
        user.id,
        actor_api_key_id="desktop-context-api-key",
        request=request,
        observed_at=observed_at + timedelta(seconds=1),
    )
    replayed = await repository.switch(
        user.id,
        actor_api_key_id="desktop-context-api-key",
        request=request,
        observed_at=observed_at + timedelta(seconds=2),
    )

    assert switched.changed is True
    assert switched.context.project_id == other_project.id
    assert switched.context.revision == 1
    assert replayed.changed is False
    assert replayed.context == switched.context


@pytest.mark.unit
async def test_workspace_context_reports_structured_unavailable_and_revision_errors(
    db_session: AsyncSession,
) -> None:
    inaccessible_user = User(
        id="desktop-context-inaccessible-user",
        email="desktop-context-inaccessible@example.com",
        hashed_password="unused",
        full_name="No Project User",
        is_active=True,
    )
    db_session.add(inaccessible_user)
    await db_session.flush()
    repository = SqlDesktopWorkspaceContextRepository(db_session)

    with pytest.raises(WorkspaceContextError) as unavailable:
        await repository.get_or_initialize(inaccessible_user.id, datetime.now(UTC))
    assert unavailable.value.code is WorkspaceContextErrorCode.UNAVAILABLE

    user, tenant, _default_project, other_project = await _seed_accessible_projects(db_session)
    await repository.get_or_initialize(user.id, datetime.now(UTC))

    with pytest.raises(WorkspaceContextError) as conflict:
        await repository.switch(
            user.id,
            actor_api_key_id=None,
            request=WorkspaceContextSwitchRequest(
                tenant_id=tenant.id,
                project_id=other_project.id,
                expected_revision=7,
                idempotency_key="desktop-context-stale-switch",
            ),
            observed_at=datetime.now(UTC),
        )
    assert conflict.value.code is WorkspaceContextErrorCode.REVISION_CONFLICT
    assert conflict.value.expected_revision == 7
    assert conflict.value.actual_revision == 0
