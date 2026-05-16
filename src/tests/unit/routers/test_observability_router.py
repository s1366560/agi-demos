"""Unit tests for observability route workspace authorization."""

from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.observability import (
    _require_observability_access,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    WorkspaceMemberModel,
    WorkspaceModel,
)


@pytest.fixture
async def observability_workspace(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> WorkspaceModel:
    workspace = WorkspaceModel(
        id=str(uuid4()),
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="Observability Workspace",
        created_by=test_user.id,
    )
    test_db.add(workspace)
    await test_db.commit()
    await test_db.refresh(workspace)
    return workspace


async def _add_workspace_member(
    test_db: AsyncSession,
    workspace: WorkspaceModel,
    user: User,
    role: str,
) -> None:
    test_db.add(
        WorkspaceMemberModel(
            id=str(uuid4()),
            workspace_id=workspace.id,
            user_id=user.id,
            role=role,
            invited_by=user.id,
        )
    )
    await test_db.commit()


@pytest.mark.unit
class TestObservabilityRouterAuthorization:
    @pytest.mark.asyncio
    async def test_non_member_cannot_read_workspace_observability(
        self,
        test_db: AsyncSession,
        observability_workspace: WorkspaceModel,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _require_observability_access(
                test_db,
                another_user,
                observability_workspace.tenant_id,
                observability_workspace.id,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_wrong_tenant_scope_returns_not_found(
        self,
        test_db: AsyncSession,
        observability_workspace: WorkspaceModel,
        test_user: User,
    ) -> None:
        await _add_workspace_member(test_db, observability_workspace, test_user, "viewer")

        with pytest.raises(HTTPException) as exc_info:
            await _require_observability_access(
                test_db,
                test_user,
                "wrong-tenant",
                observability_workspace.id,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_viewer_can_read_but_not_write_observability(
        self,
        test_db: AsyncSession,
        observability_workspace: WorkspaceModel,
        test_user: User,
    ) -> None:
        await _add_workspace_member(test_db, observability_workspace, test_user, "viewer")

        await _require_observability_access(
            test_db,
            test_user,
            observability_workspace.tenant_id,
            observability_workspace.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            await _require_observability_access(
                test_db,
                test_user,
                observability_workspace.tenant_id,
                observability_workspace.id,
                require_editor=True,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_editor_can_write_observability(
        self,
        test_db: AsyncSession,
        observability_workspace: WorkspaceModel,
        test_user: User,
    ) -> None:
        await _add_workspace_member(test_db, observability_workspace, test_user, "editor")

        await _require_observability_access(
            test_db,
            test_user,
            observability_workspace.tenant_id,
            observability_workspace.id,
            require_editor=True,
        )

    @pytest.mark.asyncio
    async def test_superuser_bypasses_workspace_membership(
        self,
        test_db: AsyncSession,
        observability_workspace: WorkspaceModel,
        another_user: User,
    ) -> None:
        another_user.is_superuser = True

        await _require_observability_access(
            test_db,
            another_user,
            observability_workspace.tenant_id,
            observability_workspace.id,
            require_editor=True,
        )
