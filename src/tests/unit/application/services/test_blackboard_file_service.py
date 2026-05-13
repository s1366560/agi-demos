"""Unit tests for blackboard file service security checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services import blackboard_file_service as service_module
from src.application.services.blackboard_file_service import BlackboardFileService
from src.domain.model.workspace.actor_identity import ActorIdentity
from src.domain.model.workspace.blackboard_file import BlackboardFile
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

    async def test_create_directory_rejects_path_traversal_name(self) -> None:
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
            await service.create_directory(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-1",
                actor_user_name="User One",
                parent_path="/",
                name="../escape",
            )

        file_repo.save.assert_not_awaited()

    async def test_create_directory_uses_display_name_and_checks_duplicates(self) -> None:
        file_repo = AsyncMock()
        workspace_repo = AsyncMock()
        workspace_member_repo = AsyncMock()
        workspace_repo.find_by_id.return_value = _make_workspace()
        workspace_member_repo.find_by_workspace_and_user.return_value = SimpleNamespace(
            role=WorkspaceRole.EDITOR
        )
        file_repo.list_by_workspace.return_value = []
        file_repo.save.side_effect = lambda directory: directory

        service = BlackboardFileService(
            file_repo=file_repo,
            workspace_repo=workspace_repo,
            workspace_member_repo=workspace_member_repo,
        )

        directory = await service.create_directory(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
            actor_user_name="User One",
            parent_path="/docs",
            name="notes",
        )

        assert directory.parent_path == "/docs/"
        assert directory.name == "notes"
        assert directory.uploader_name == "User One"
        file_repo.list_by_workspace.assert_awaited_once_with("workspace-1", "/docs/")

    async def test_upload_file_rejects_duplicate_name(
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
        file_repo.list_by_workspace.return_value = [SimpleNamespace(name="report.txt")]

        service = BlackboardFileService(
            file_repo=file_repo,
            workspace_repo=workspace_repo,
            workspace_member_repo=workspace_member_repo,
        )

        with pytest.raises(ValueError, match="already exists"):
            await service.upload_file(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-1",
                actor_user_name="User One",
                parent_path="/",
                filename="report.txt",
                content=b"duplicate",
            )

        file_repo.save.assert_not_awaited()
        assert list(tmp_path.rglob("*")) == []

    async def test_delete_directory_rejects_non_empty_directory(self) -> None:
        file_repo = AsyncMock()
        workspace_repo = AsyncMock()
        workspace_member_repo = AsyncMock()
        workspace_repo.find_by_id.return_value = _make_workspace()
        workspace_member_repo.find_by_workspace_and_user.return_value = SimpleNamespace(
            role=WorkspaceRole.EDITOR
        )
        file_repo.find_by_id.return_value = SimpleNamespace(
            workspace_id="workspace-1",
            is_directory=True,
            parent_path="/",
            name="docs",
        )
        file_repo.list_by_workspace.return_value = [SimpleNamespace(name="report.txt")]

        service = BlackboardFileService(
            file_repo=file_repo,
            workspace_repo=workspace_repo,
            workspace_member_repo=workspace_member_repo,
        )

        with pytest.raises(ValueError, match="Directory is not empty"):
            await service.delete_file(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-1",
                file_id="dir-1",
            )

        file_repo.list_by_workspace.assert_awaited_once_with("workspace-1", "/docs/")
        file_repo.delete.assert_not_awaited()

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


# =============================================================================
# Rename / Move / Copy / Recursive Delete (M2 #C)
# =============================================================================




def _make_file(
    *,
    file_id: str = "file-1",
    workspace_id: str = "workspace-1",
    parent_path: str = "/",
    name: str = "report.txt",
    is_directory: bool = False,
    storage_key: str = "",
    checksum: str | None = None,
) -> BlackboardFile:
    return BlackboardFile(
        id=file_id,
        workspace_id=workspace_id,
        parent_path=parent_path,
        name=name,
        is_directory=is_directory,
        file_size=10,
        content_type="text/plain",
        storage_key=storage_key,
        uploader_type="user",
        uploader_id="user-1",
        uploader_name="User One",
        checksum_sha256=checksum,
    )


def _editor_service(file_repo: AsyncMock) -> BlackboardFileService:
    workspace_repo = AsyncMock()
    workspace_member_repo = AsyncMock()
    workspace_repo.find_by_id.return_value = _make_workspace()
    workspace_member_repo.find_by_workspace_and_user.return_value = SimpleNamespace(
        role=WorkspaceRole.EDITOR
    )
    return BlackboardFileService(
        file_repo=file_repo,
        workspace_repo=workspace_repo,
        workspace_member_repo=workspace_member_repo,
    )


@pytest.mark.unit
class TestBlackboardFileRenameMoveCopy:
    async def test_rename_file_persists_new_name(self) -> None:
        file_repo = AsyncMock()
        file_repo.find_by_id.return_value = _make_file()
        file_repo.list_by_workspace.return_value = []
        file_repo.save.side_effect = lambda f: f

        service = _editor_service(file_repo)
        renamed = await service.rename_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
            file_id="file-1",
            new_name="renamed.txt",
        )
        assert renamed.name == "renamed.txt"
        # No bulk_update_parent_path for a leaf file.
        file_repo.bulk_update_parent_path.assert_not_awaited()

    async def test_rename_directory_rewrites_descendant_prefixes(self) -> None:
        file_repo = AsyncMock()
        file_repo.find_by_id.return_value = _make_file(
            file_id="dir-1", name="docs", is_directory=True
        )
        file_repo.list_by_workspace.return_value = []
        file_repo.save.side_effect = lambda f: f
        file_repo.bulk_update_parent_path.return_value = 3

        service = _editor_service(file_repo)
        await service.rename_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
            file_id="dir-1",
            new_name="papers",
        )
        file_repo.bulk_update_parent_path.assert_awaited_once_with(
            "workspace-1", "/docs/", "/papers/"
        )

    async def test_rename_rejects_duplicate_sibling_name(self) -> None:
        file_repo = AsyncMock()
        file_repo.find_by_id.return_value = _make_file()
        file_repo.list_by_workspace.return_value = [
            SimpleNamespace(name="taken.txt")
        ]
        service = _editor_service(file_repo)
        with pytest.raises(ValueError, match="already exists"):
            await service.rename_file(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-1",
                file_id="file-1",
                new_name="taken.txt",
            )

    async def test_move_file_blocks_into_own_subtree(self) -> None:
        file_repo = AsyncMock()
        file_repo.find_by_id.return_value = _make_file(
            file_id="dir-1", name="docs", is_directory=True
        )
        service = _editor_service(file_repo)
        with pytest.raises(ValueError, match="into itself"):
            await service.move_file(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_user_id="user-1",
                file_id="dir-1",
                new_parent_path="/docs/sub/",
            )

    async def test_move_directory_rewrites_descendant_prefixes(self) -> None:
        file_repo = AsyncMock()
        file_repo.find_by_id.return_value = _make_file(
            file_id="dir-1", name="docs", parent_path="/", is_directory=True
        )

        # list_by_workspace is called twice: first by _require_directory_exists
        # to validate the target's parent, then by _ensure_name_available to
        # check sibling collision in the target dir.
        file_repo.list_by_workspace.side_effect = [
            [SimpleNamespace(name="archive", is_directory=True)],  # /archive exists
            [],  # no sibling collision in /archive/
        ]
        file_repo.save.side_effect = lambda f: f

        service = _editor_service(file_repo)
        moved = await service.move_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
            file_id="dir-1",
            new_parent_path="/archive/",
        )
        assert moved.parent_path == "/archive/"
        file_repo.bulk_update_parent_path.assert_awaited_once_with(
            "workspace-1", "/docs/", "/archive/docs/"
        )

    async def test_recursive_delete_removes_descendants(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service_module, "STORAGE_ROOT", tmp_path)
        file_repo = AsyncMock()
        dir_row = _make_file(file_id="dir-1", name="docs", is_directory=True)
        file_repo.find_by_id.return_value = dir_row
        file_repo.list_by_workspace.return_value = [
            _make_file(file_id="leaf-1", parent_path="/docs/", name="a.txt")
        ]
        file_repo.find_descendants.return_value = [
            _make_file(
                file_id="leaf-1",
                parent_path="/docs/",
                name="a.txt",
                storage_key="leaf-1/a.txt",
            )
        ]
        # write a stub on-disk artifact so the cleanup path is exercised.
        leaf_dir = tmp_path / "workspace-1" / "leaf-1"
        leaf_dir.mkdir(parents=True)
        (leaf_dir / "a.txt").write_bytes(b"hi")
        file_repo.delete.return_value = True

        service = _editor_service(file_repo)
        deleted, was_directory = await service.delete_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
            file_id="dir-1",
            recursive=True,
        )
        assert deleted is True
        assert was_directory is True
        assert file_repo.delete.await_count == 2  # leaf + root
        # On-disk leaf should be gone.
        assert not (leaf_dir / "a.txt").exists()

    async def test_copy_file_clones_content_and_checksum(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service_module, "STORAGE_ROOT", tmp_path)
        file_repo = AsyncMock()
        src = _make_file(
            file_id="file-1",
            name="report.txt",
            storage_key="file-1/report.txt",
            checksum="a" * 64,
        )
        file_repo.find_by_id.return_value = src
        file_repo.list_by_workspace.return_value = []
        file_repo.save.side_effect = lambda f: f
        # Seed source on disk.
        src_dir = tmp_path / "workspace-1" / "file-1"
        src_dir.mkdir(parents=True)
        (src_dir / "report.txt").write_bytes(b"payload")

        service = _editor_service(file_repo)
        copy = await service.copy_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
            actor_user_name="User One",
            file_id="file-1",
            target_parent_path="/",
            new_name="report-copy.txt",
        )
        assert copy.name == "report-copy.txt"
        assert copy.checksum_sha256 == "a" * 64
        # New on-disk content exists under the cloned id.
        copy_path = tmp_path / "workspace-1" / copy.id / "report-copy.txt"
        assert copy_path.read_bytes() == b"payload"


# =============================================================================
# Agent uploader provenance (M2 #B)
# =============================================================================




@pytest.mark.unit
class TestBlackboardFileAgentUpload:
    async def test_upload_with_agent_actor_records_agent_provenance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service_module, "STORAGE_ROOT", tmp_path)
        file_repo = AsyncMock()
        file_repo.list_by_workspace.return_value = []
        file_repo.save.side_effect = lambda f: f

        service = _editor_service(file_repo)
        bb_file = await service.upload_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
            actor_user_name="User One",
            parent_path="/",
            filename="note.txt",
            content=b"hi",
            actor=ActorIdentity(kind="agent", id="agent-99", label="Researcher"),
        )
        assert bb_file.uploader_type == "agent"
        assert bb_file.uploader_id == "agent-99"
        assert bb_file.uploader_name == "Researcher"

    async def test_upload_without_actor_defaults_to_user(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service_module, "STORAGE_ROOT", tmp_path)
        file_repo = AsyncMock()
        file_repo.list_by_workspace.return_value = []
        file_repo.save.side_effect = lambda f: f

        service = _editor_service(file_repo)
        bb_file = await service.upload_file(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
            actor_user_name="User One",
            parent_path="/",
            filename="note.txt",
            content=b"hi",
        )
        assert bb_file.uploader_type == "user"
        assert bb_file.uploader_id == "user-1"
        assert bb_file.uploader_name == "User One"
