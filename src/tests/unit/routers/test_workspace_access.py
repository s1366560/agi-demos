"""Unit tests for shared path-scoped workspace router authorization."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_cyber_schemas import CyberGeneCreate
from src.infrastructure.adapters.primary.web.routers.cyber_genes import create_gene
from src.infrastructure.adapters.primary.web.routers.workspace_access import (
    require_workspace_access,
)
from src.infrastructure.adapters.primary.web.routers.workspace_chat import list_messages
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    WorkspaceMemberModel,
    WorkspaceModel,
)


@pytest.fixture
async def routed_workspace(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> WorkspaceModel:
    workspace = WorkspaceModel(
        id=str(uuid4()),
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="Routed Workspace",
        created_by=test_user.id,
    )
    test_db.add(workspace)
    await test_db.commit()
    await test_db.refresh(workspace)
    return workspace


async def _add_member(
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
class TestWorkspaceAccess:
    @pytest.mark.asyncio
    async def test_non_member_is_rejected(
        self,
        test_db: AsyncSession,
        routed_workspace: WorkspaceModel,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await require_workspace_access(
                test_db,
                another_user,
                routed_workspace.tenant_id,
                routed_workspace.project_id,
                routed_workspace.id,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_wrong_path_scope_returns_not_found(
        self,
        test_db: AsyncSession,
        routed_workspace: WorkspaceModel,
        test_user: User,
    ) -> None:
        await _add_member(test_db, routed_workspace, test_user, "viewer")

        with pytest.raises(HTTPException) as exc_info:
            await require_workspace_access(
                test_db,
                test_user,
                routed_workspace.tenant_id,
                "wrong-project",
                routed_workspace.id,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_viewer_can_read_but_not_write(
        self,
        test_db: AsyncSession,
        routed_workspace: WorkspaceModel,
        test_user: User,
    ) -> None:
        await _add_member(test_db, routed_workspace, test_user, "viewer")

        await require_workspace_access(
            test_db,
            test_user,
            routed_workspace.tenant_id,
            routed_workspace.project_id,
            routed_workspace.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            await require_workspace_access(
                test_db,
                test_user,
                routed_workspace.tenant_id,
                routed_workspace.project_id,
                routed_workspace.id,
                require_editor=True,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_editor_can_write(
        self,
        test_db: AsyncSession,
        routed_workspace: WorkspaceModel,
        test_user: User,
    ) -> None:
        await _add_member(test_db, routed_workspace, test_user, "editor")

        await require_workspace_access(
            test_db,
            test_user,
            routed_workspace.tenant_id,
            routed_workspace.project_id,
            routed_workspace.id,
            require_editor=True,
        )

    @pytest.mark.asyncio
    async def test_superuser_bypasses_membership_lookup(
        self,
        test_db: AsyncSession,
        routed_workspace: WorkspaceModel,
        another_user: User,
    ) -> None:
        another_user.is_superuser = True

        await require_workspace_access(
            test_db,
            another_user,
            routed_workspace.tenant_id,
            routed_workspace.project_id,
            routed_workspace.id,
            require_editor=True,
        )


@pytest.mark.unit
class TestWorkspaceScopedRoutes:
    @pytest.mark.asyncio
    async def test_chat_list_rejects_non_member_before_service_lookup(
        self,
        test_db: AsyncSession,
        routed_workspace: WorkspaceModel,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await list_messages(
                routed_workspace.tenant_id,
                routed_workspace.project_id,
                routed_workspace.id,
                SimpleNamespace(),
                current_user=another_user,
                db=test_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_gene_create_rejects_viewer_before_container_lookup(
        self,
        test_db: AsyncSession,
        routed_workspace: WorkspaceModel,
        test_user: User,
    ) -> None:
        await _add_member(test_db, routed_workspace, test_user, "viewer")

        with pytest.raises(HTTPException) as exc_info:
            await create_gene(
                routed_workspace.tenant_id,
                routed_workspace.project_id,
                routed_workspace.id,
                CyberGeneCreate(name="Viewer Gene"),
                SimpleNamespace(),
                current_user=test_user,
                db=test_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
