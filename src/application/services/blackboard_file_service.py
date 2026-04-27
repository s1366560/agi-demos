"""Application service for workspace blackboard file management."""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
from pathlib import Path

from src.domain.model.workspace.blackboard_file import BlackboardFile
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.ports.repositories.workspace.blackboard_file_repository import (
    BlackboardFileRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository

logger = logging.getLogger(__name__)

BLOCKED_SEGMENTS = {
    "credentials",
    "node_modules",
    ".env",
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
STORAGE_ROOT = Path("data/workspace-files")


def _validate_path(path: str) -> str:
    """Validate and normalize a file path. Prevent traversal attacks."""
    raw_path = (path or "/").replace("\\", "/").strip()
    raw_parts = [part for part in raw_path.split("/") if part not in {"", "."}]
    if any(part == ".." for part in raw_parts):
        raise ValueError("Path traversal detected")
    for part in raw_parts:
        if part.lower() in BLOCKED_SEGMENTS:
            raise ValueError(f"Blocked path segment: {part}")
    if not raw_parts:
        return "/"
    normalized = os.path.normpath("/".join(raw_parts)).replace("\\", "/")
    return f"/{normalized.strip('/')}/"


def _validate_filename(filename: str) -> str:
    """Validate a filename to prevent path traversal and unsafe writes."""
    normalized = filename.replace("\\", "/")
    safe_name = Path(normalized).name
    if not normalized or safe_name != normalized or safe_name in {"", ".", ".."}:
        raise ValueError("Invalid filename")
    if "\x00" in safe_name:
        raise ValueError("Invalid filename")
    if safe_name.lower() in BLOCKED_SEGMENTS:
        raise ValueError(f"Blocked path segment: {safe_name}")
    return safe_name


def _join_child_path(parent_path: str, name: str) -> str:
    """Build the canonical parent path for a child directory."""
    return _validate_path(f"{parent_path.rstrip('/')}/{name}")


def _resolve_storage_path(workspace_id: str, storage_key: str) -> Path:
    """Resolve a storage key beneath the workspace storage root."""
    base_dir = (STORAGE_ROOT / workspace_id).resolve()
    storage_path = (base_dir / storage_key).resolve()
    try:
        storage_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError("Invalid storage path") from exc
    return storage_path


class BlackboardFileService:
    """Manages workspace blackboard files with local filesystem storage."""

    def __init__(
        self,
        file_repo: BlackboardFileRepository,
        workspace_repo: WorkspaceRepository,
        workspace_member_repo: WorkspaceMemberRepository,
    ) -> None:
        self._file_repo = file_repo
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo

    async def list_files(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        parent_path: str = "/",
    ) -> list[BlackboardFile]:
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_member(workspace.id, actor_user_id)
        safe_path = _validate_path(parent_path)
        return await self._file_repo.list_by_workspace(workspace_id, safe_path)

    async def create_directory(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        actor_user_name: str | None,
        parent_path: str,
        name: str,
    ) -> BlackboardFile:
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_editor(workspace.id, actor_user_id)
        safe_path = _validate_path(parent_path)
        safe_name = _validate_filename(name.strip())
        await self._ensure_name_available(workspace.id, safe_path, safe_name)

        directory = BlackboardFile(
            id=BlackboardFile.generate_id(),
            workspace_id=workspace.id,
            parent_path=safe_path,
            name=safe_name,
            is_directory=True,
            uploader_type="user",
            uploader_id=actor_user_id,
            uploader_name=actor_user_name or actor_user_id,
        )
        return await self._file_repo.save(directory)

    async def upload_file(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        actor_user_name: str,
        parent_path: str,
        filename: str,
        content: bytes,
    ) -> BlackboardFile:
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_editor(workspace.id, actor_user_id)
        safe_path = _validate_path(parent_path)

        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"File exceeds maximum size of {MAX_FILE_SIZE} bytes")

        safe_filename = _validate_filename(filename)
        await self._ensure_name_available(workspace.id, safe_path, safe_filename)
        content_type = mimetypes.guess_type(safe_filename)[0] or "application/octet-stream"
        file_id = BlackboardFile.generate_id()
        storage_key = f"{file_id}/{safe_filename}"

        storage_dir = STORAGE_ROOT / workspace.id / file_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = _resolve_storage_path(workspace.id, storage_key)
        storage_path.write_bytes(content)

        bb_file = BlackboardFile(
            id=file_id,
            workspace_id=workspace.id,
            parent_path=safe_path,
            name=safe_filename,
            is_directory=False,
            file_size=len(content),
            content_type=content_type,
            storage_key=storage_key,
            uploader_type="user",
            uploader_id=actor_user_id,
            uploader_name=actor_user_name,
        )
        return await self._file_repo.save(bb_file)

    async def read_file(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        file_id: str,
    ) -> tuple[bytes, str, str]:
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_member(workspace.id, actor_user_id)
        bb_file = await self._file_repo.find_by_id(file_id)
        if bb_file is None or bb_file.workspace_id != workspace_id:
            raise ValueError("File not found")
        if bb_file.is_directory:
            raise ValueError("Cannot read directory content")

        storage_path = _resolve_storage_path(workspace_id, bb_file.storage_key)
        if not storage_path.exists():
            raise ValueError("File content not found on disk")
        return storage_path.read_bytes(), bb_file.content_type, bb_file.name

    async def delete_file(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        file_id: str,
    ) -> bool:
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_editor(workspace.id, actor_user_id)
        bb_file = await self._file_repo.find_by_id(file_id)
        if bb_file is None or bb_file.workspace_id != workspace_id:
            raise ValueError("File not found")

        if bb_file.is_directory:
            child_path = _join_child_path(bb_file.parent_path, bb_file.name)
            children = await self._file_repo.list_by_workspace(workspace.id, child_path)
            if children:
                raise ValueError("Directory is not empty")
        elif bb_file.storage_key:
            storage_path = _resolve_storage_path(workspace_id, bb_file.storage_key)
            if storage_path.exists():
                storage_path.unlink(missing_ok=True)
            parent_dir = storage_path.parent
            if parent_dir.exists() and not any(parent_dir.iterdir()):
                shutil.rmtree(parent_dir, ignore_errors=True)

        return await self._file_repo.delete(file_id)

    async def _ensure_name_available(self, workspace_id: str, parent_path: str, name: str) -> None:
        siblings = await self._file_repo.list_by_workspace(workspace_id, parent_path)
        if any(item.name == name for item in siblings):
            raise ValueError("A file or folder with this name already exists")

    async def _require_workspace_scope(
        self, tenant_id: str, project_id: str, workspace_id: str
    ) -> Workspace:
        workspace = await self._workspace_repo.find_by_id(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id} not found")
        if workspace.tenant_id != tenant_id or workspace.project_id != project_id:
            raise ValueError("Workspace scope mismatch")
        return workspace

    async def _require_member(self, workspace_id: str, user_id: str) -> None:
        member = await self._workspace_member_repo.find_by_workspace_and_user(
            workspace_id=workspace_id, user_id=user_id
        )
        if member is None:
            raise PermissionError("Not a workspace member")

    async def _require_editor(self, workspace_id: str, user_id: str) -> None:
        member = await self._workspace_member_repo.find_by_workspace_and_user(
            workspace_id=workspace_id, user_id=user_id
        )
        if member is None:
            raise PermissionError("Not a workspace member")
        if member.role not in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
            raise PermissionError("Insufficient permission to manage files")
