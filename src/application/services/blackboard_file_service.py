"""Application service for workspace blackboard file management."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from src.domain.model.workspace.actor_identity import ActorIdentity
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
DOWNLOAD_CHUNK_SIZE = 64 * 1024  # 64 KiB
# Cap on the number of rows (root + descendants) a single directory copy may
# touch synchronously. Larger trees should be staged via a future async job.
MAX_COPY_ENTRIES = 500
# Files at or below this size are eligible for opportunistic SHA-256 backfill on
# read. Larger files emit a weak ETag derived from id+size to avoid blocking
# downloads on long hash computations.
LAZY_HASH_MAX_BYTES = 25 * 1024 * 1024  # 25 MiB


@dataclass(frozen=True, kw_only=True)
class BlackboardFileStream:
    """Streaming descriptor for a blackboard file download."""

    file_id: str
    filename: str
    content_type: str
    file_size: int
    checksum_sha256: str | None
    iterator: AsyncIterator[bytes]


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


def _resolve_uploader(
    actor: ActorIdentity | None,
    actor_user_id: str,
    actor_user_name: str | None,
) -> tuple[str, str, str]:
    """Pick (uploader_type, uploader_id, uploader_name) from the actor or user fallback."""
    if actor is not None:
        return actor.kind, actor.id, actor.label
    return "user", actor_user_id, actor_user_name or actor_user_id


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
        actor: ActorIdentity | None = None,
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
        checksum_sha256 = hashlib.sha256(content).hexdigest()

        # Membership and permission are always checked against the human user;
        # provenance fields reflect the acting principal (user OR agent).
        uploader_type, uploader_id, uploader_name = _resolve_uploader(
            actor, actor_user_id, actor_user_name
        )

        bb_file = BlackboardFile(
            id=file_id,
            workspace_id=workspace.id,
            parent_path=safe_path,
            name=safe_filename,
            is_directory=False,
            file_size=len(content),
            content_type=content_type,
            storage_key=storage_key,
            uploader_type=uploader_type,
            uploader_id=uploader_id,
            uploader_name=uploader_name,
            checksum_sha256=checksum_sha256,
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

    async def open_file_stream(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        file_id: str,
    ) -> BlackboardFileStream:
        """Authorize and open a streaming download for a blackboard file."""
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

        # Opportunistic SHA-256 backfill: only for moderately-sized rows missing
        # a checksum. The hash is captured while streaming and persisted via an
        # idempotent UPDATE after the stream completes.
        eligible_for_backfill = (
            bb_file.checksum_sha256 is None and bb_file.file_size <= LAZY_HASH_MAX_BYTES
        )
        repo = self._file_repo

        async def _iter_chunks() -> AsyncIterator[bytes]:
            loop = asyncio.get_running_loop()
            handle = await loop.run_in_executor(None, storage_path.open, "rb")
            hasher = hashlib.sha256() if eligible_for_backfill else None
            try:
                while True:
                    chunk = await loop.run_in_executor(None, handle.read, DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    if hasher is not None:
                        hasher.update(chunk)
                    yield chunk
            finally:
                await loop.run_in_executor(None, handle.close)
                if hasher is not None:
                    try:
                        await repo.update_checksum(bb_file.id, hasher.hexdigest())
                    except Exception:
                        logger.exception(
                            "blackboard checksum backfill failed for %s", bb_file.id
                        )

        return BlackboardFileStream(
            file_id=bb_file.id,
            filename=bb_file.name,
            content_type=bb_file.content_type,
            file_size=bb_file.file_size,
            checksum_sha256=bb_file.checksum_sha256,
            iterator=_iter_chunks(),
        )

    async def delete_file(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        file_id: str,
        recursive: bool = False,
    ) -> tuple[bool, bool]:
        """Delete a file or directory.

        Returns ``(deleted, was_directory)`` so callers can pick the right
        event type without needing a separate read.
        """
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_editor(workspace.id, actor_user_id)
        bb_file = await self._file_repo.find_by_id(file_id)
        if bb_file is None or bb_file.workspace_id != workspace_id:
            raise ValueError("File not found")

        was_directory = bb_file.is_directory
        if bb_file.is_directory:
            child_path = _join_child_path(bb_file.parent_path, bb_file.name)
            children = await self._file_repo.list_by_workspace(workspace.id, child_path)
            if children and not recursive:
                raise ValueError("Directory is not empty")
            if recursive:
                # Cascading delete: every descendant + on-disk content.
                descendants = await self._file_repo.find_descendants(
                    workspace.id, child_path
                )
                # Delete leaves before parents is unnecessary at the DB level
                # because we have no FKs between rows; but on-disk content must
                # be cleaned up regardless of order.
                for desc in descendants:
                    if not desc.is_directory and desc.storage_key:
                        self._remove_on_disk(workspace_id, desc.storage_key)
                    await self._file_repo.delete(desc.id)
        elif bb_file.storage_key:
            self._remove_on_disk(workspace_id, bb_file.storage_key)

        deleted = await self._file_repo.delete(file_id)
        return deleted, was_directory

    async def rename_file(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        file_id: str,
        new_name: str,
    ) -> BlackboardFile:
        """Rename a file or directory in place.

        For directories, descendant ``parent_path`` rows are rewritten in a
        single SQL UPDATE so the operation is atomic from the caller's view.
        """
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_editor(workspace.id, actor_user_id)
        bb_file = await self._file_repo.find_by_id(file_id)
        if bb_file is None or bb_file.workspace_id != workspace_id:
            raise ValueError("File not found")

        safe_name = _validate_filename(new_name.strip())
        if safe_name == bb_file.name:
            return bb_file
        await self._ensure_name_available(workspace.id, bb_file.parent_path, safe_name)

        if bb_file.is_directory:
            old_prefix = _join_child_path(bb_file.parent_path, bb_file.name)
            new_prefix = _join_child_path(bb_file.parent_path, safe_name)
            await self._file_repo.bulk_update_parent_path(
                workspace.id, old_prefix, new_prefix
            )

        renamed = self._with_changes(bb_file, name=safe_name)
        return await self._file_repo.save(renamed)

    async def move_file(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        file_id: str,
        new_parent_path: str,
    ) -> BlackboardFile:
        """Move a file or directory into a different parent directory."""
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_editor(workspace.id, actor_user_id)
        bb_file = await self._file_repo.find_by_id(file_id)
        if bb_file is None or bb_file.workspace_id != workspace_id:
            raise ValueError("File not found")

        target_parent = _validate_path(new_parent_path)
        if target_parent == bb_file.parent_path:
            return bb_file

        # Block moving a directory into its own subtree.
        if bb_file.is_directory:
            own_prefix = _join_child_path(bb_file.parent_path, bb_file.name)
            if target_parent == own_prefix or target_parent.startswith(own_prefix):
                raise ValueError("Cannot move a directory into itself")

        # Verify the destination directory exists (root "/" is always valid).
        if target_parent != "/":
            await self._require_directory_exists(workspace.id, target_parent)

        await self._ensure_name_available(workspace.id, target_parent, bb_file.name)

        if bb_file.is_directory:
            old_prefix = _join_child_path(bb_file.parent_path, bb_file.name)
            new_prefix = _join_child_path(target_parent, bb_file.name)
            await self._file_repo.bulk_update_parent_path(
                workspace.id, old_prefix, new_prefix
            )

        moved = self._with_changes(bb_file, parent_path=target_parent)
        return await self._file_repo.save(moved)

    async def copy_file(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        actor_user_name: str,
        file_id: str,
        target_parent_path: str,
        new_name: str | None = None,
    ) -> BlackboardFile:
        """Copy a file or directory subtree.

        Directory copies are capped at ``MAX_COPY_ENTRIES`` to keep the
        operation bounded; larger trees should be staged client-side or via a
        future async job.
        """
        workspace = await self._require_workspace_scope(tenant_id, project_id, workspace_id)
        await self._require_editor(workspace.id, actor_user_id)
        bb_file = await self._file_repo.find_by_id(file_id)
        if bb_file is None or bb_file.workspace_id != workspace_id:
            raise ValueError("File not found")

        target_parent = _validate_path(target_parent_path)
        if target_parent != "/":
            await self._require_directory_exists(workspace.id, target_parent)

        copy_name = _validate_filename((new_name or bb_file.name).strip())
        await self._ensure_name_available(workspace.id, target_parent, copy_name)

        if not bb_file.is_directory:
            return await self._copy_single_file(
                workspace_id=workspace.id,
                source=bb_file,
                target_parent=target_parent,
                target_name=copy_name,
                actor_user_id=actor_user_id,
                actor_user_name=actor_user_name,
            )

        # Directory copy: block self-copy into own subtree.
        own_prefix = _join_child_path(bb_file.parent_path, bb_file.name)
        if target_parent == own_prefix or target_parent.startswith(own_prefix):
            raise ValueError("Cannot copy a directory into itself")

        descendants = await self._file_repo.find_descendants(workspace.id, own_prefix)
        if 1 + len(descendants) > MAX_COPY_ENTRIES:
            raise ValueError(
                f"Directory copy exceeds limit of {MAX_COPY_ENTRIES} entries"
            )

        # Materialize the new root directory first so its child_prefix is known.
        new_root = BlackboardFile(
            id=BlackboardFile.generate_id(),
            workspace_id=workspace.id,
            parent_path=target_parent,
            name=copy_name,
            is_directory=True,
            uploader_type="user",
            uploader_id=actor_user_id,
            uploader_name=actor_user_name or actor_user_id,
        )
        new_root = await self._file_repo.save(new_root)

        new_prefix = _join_child_path(target_parent, copy_name)
        for desc in descendants:
            # Rewrite parent_path to the destination subtree.
            mapped_parent = new_prefix + desc.parent_path[len(own_prefix):]
            if desc.is_directory:
                clone = BlackboardFile(
                    id=BlackboardFile.generate_id(),
                    workspace_id=workspace.id,
                    parent_path=mapped_parent,
                    name=desc.name,
                    is_directory=True,
                    uploader_type="user",
                    uploader_id=actor_user_id,
                    uploader_name=actor_user_name or actor_user_id,
                )
                await self._file_repo.save(clone)
            else:
                await self._copy_single_file(
                    workspace_id=workspace.id,
                    source=desc,
                    target_parent=mapped_parent,
                    target_name=desc.name,
                    actor_user_id=actor_user_id,
                    actor_user_name=actor_user_name,
                )

        return new_root

    async def _copy_single_file(
        self,
        *,
        workspace_id: str,
        source: BlackboardFile,
        target_parent: str,
        target_name: str,
        actor_user_id: str,
        actor_user_name: str,
    ) -> BlackboardFile:
        """Copy on-disk content + persist a new row carrying the same checksum."""
        new_id = BlackboardFile.generate_id()
        new_storage_key = f"{new_id}/{target_name}"
        new_storage_path = _resolve_storage_path(workspace_id, new_storage_key)
        new_storage_path.parent.mkdir(parents=True, exist_ok=True)
        if source.storage_key:
            src_path = _resolve_storage_path(workspace_id, source.storage_key)
            if src_path.exists():
                shutil.copyfile(src_path, new_storage_path)
        clone = BlackboardFile(
            id=new_id,
            workspace_id=workspace_id,
            parent_path=target_parent,
            name=target_name,
            is_directory=False,
            file_size=source.file_size,
            content_type=source.content_type,
            storage_key=new_storage_key,
            uploader_type="user",
            uploader_id=actor_user_id,
            uploader_name=actor_user_name or actor_user_id,
            checksum_sha256=source.checksum_sha256,
        )
        return await self._file_repo.save(clone)

    def _remove_on_disk(self, workspace_id: str, storage_key: str) -> None:
        storage_path = _resolve_storage_path(workspace_id, storage_key)
        if storage_path.exists():
            storage_path.unlink(missing_ok=True)
        parent_dir = storage_path.parent
        if parent_dir.exists() and not any(parent_dir.iterdir()):
            shutil.rmtree(parent_dir, ignore_errors=True)

    async def _require_directory_exists(self, workspace_id: str, path: str) -> None:
        """Verify ``path`` (canonical, ends with /) is an existing directory row."""
        if path == "/":
            return
        # path is "/a/b/" → parent="/a/", name="b"
        trimmed = path.rstrip("/")
        parent, _, name = trimmed.rpartition("/")
        parent_path = (parent + "/") if parent else "/"
        siblings = await self._file_repo.list_by_workspace(workspace_id, parent_path)
        if not any(s.name == name and s.is_directory for s in siblings):
            raise ValueError(f"Directory not found: {path}")

    @staticmethod
    def _with_changes(file: BlackboardFile, **changes: object) -> BlackboardFile:
        """Return a new BlackboardFile with the requested field overrides.

        Honors immutability — never mutates the input dataclass.
        """
        from dataclasses import replace

        return replace(file, **changes)  # type: ignore[arg-type]

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
