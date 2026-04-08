"""Unit tests for blackboard file service security checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services import blackboard_file_service as service_module
from src.application.services.blackboard_file_service import BlackboardFileService
from src.domain.model.workspace.workspace_role import WorkspaceRole


def _make_workspace() -> SimpleNamespace:
    return SimpleNamespace(id="workspace-1", tenant_id="tenant-1", project_id="project-1")


@pytest.mark.unit
class TestBlackboardFileServiceSecurity:
    async def test_list_files_requires_workspace_member(self) -> None:
        file_repo = AsyncMock()
        workspace_repo = AsyncMock()
        workspace_member_repo = AsyncMock()
        workspace_repo.find_by_id.return_value = _make_workspace()
        workspace_member_repo.find_by_workspace_and_user.return_value = None

        service = BlackboardFileService(
            file_repo=file_repo,
            workspace_repo=workspace_repo,
            workspace_member_repo=workspace_member_repo,
        )

        with pytest.raises(PermissionError, match="Not a workspace member"):
            await service.list_files(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-2",
                parent_path="/",
            )

        file_repo.list_by_workspace.assert_not_awaited()

    async def test_read_file_requires_workspace_member(self) -> None:
        file_repo = AsyncMock()
        workspace_repo = AsyncMock()
        workspace_member_repo = AsyncMock()
        workspace_repo.find_by_id.return_value = _make_workspace()
        workspace_member_repo.find_by_workspace_and_user.return_value = None

        service = BlackboardFileService(
            file_repo=file_repo,
            workspace_repo=workspace_repo,
            workspace_member_repo=workspace_member_repo,
        )

        with pytest.raises(PermissionError, match="Not a workspace member"):
            await service.read_file(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-2",
                file_id="file-1",
            )

        file_repo.find_by_id.assert_not_awaited()

    async def test_upload_file_rejects_path_traversal_filename(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(service_module, "STORAGE_ROOT", tmp_path)

        file_repo = AsyncMock()
        workspace_repo = AsyncMock()
        workspace_member_repo = AsyncMock()
        workspace_repo.find_by_id.return_value = _make_workspace()
        workspace_member_repo.find_by_workspace_and_user.return_value = SimpleNamespace(
            role=WorkspaceRole.EDITOR
        )

        service = BlackboardFileService(
            file_repo=file_repo,
            workspace_repo=workspace_repo,
            workspace_member_repo=workspace_member_repo,
        )

        with pytest.raises(ValueError, match="Invalid filename"):
            await service.upload_file(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-1",
                actor_user_name="User One",
                parent_path="/",
                filename="../escape.txt",
                content=b"blocked",
            )

        file_repo.save.assert_not_awaited()

    async def test_read_file_rejects_invalid_persisted_storage_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(service_module, "STORAGE_ROOT", tmp_path)

        file_repo = AsyncMock()
        workspace_repo = AsyncMock()
        workspace_member_repo = AsyncMock()
        workspace_repo.find_by_id.return_value = _make_workspace()
        workspace_member_repo.find_by_workspace_and_user.return_value = SimpleNamespace(
            role=WorkspaceRole.EDITOR
        )
        file_repo.find_by_id.return_value = SimpleNamespace(
            workspace_id="workspace-1",
            is_directory=False,
            storage_key="../outside.txt",
            content_type="text/plain",
        )

        service = BlackboardFileService(
            file_repo=file_repo,
            workspace_repo=workspace_repo,
            workspace_member_repo=workspace_member_repo,
        )

        with pytest.raises(ValueError, match="Invalid storage path"):
            await service.read_file(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-1",
                file_id="file-1",
            )

    async def test_delete_file_rejects_invalid_persisted_storage_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(service_module, "STORAGE_ROOT", tmp_path)

        file_repo = AsyncMock()
        workspace_repo = AsyncMock()
        workspace_member_repo = AsyncMock()
        workspace_repo.find_by_id.return_value = _make_workspace()
        workspace_member_repo.find_by_workspace_and_user.return_value = SimpleNamespace(
            role=WorkspaceRole.EDITOR
        )
        file_repo.find_by_id.return_value = SimpleNamespace(
            workspace_id="workspace-1",
            is_directory=False,
            storage_key="../outside.txt",
        )

        service = BlackboardFileService(
            file_repo=file_repo,
            workspace_repo=workspace_repo,
            workspace_member_repo=workspace_member_repo,
        )

        with pytest.raises(ValueError, match="Invalid storage path"):
            await service.delete_file(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-1",
                file_id="file-1",
            )

        file_repo.delete.assert_not_awaited()
