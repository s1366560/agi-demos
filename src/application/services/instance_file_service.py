"""Instance file management service.

Provides file browsing, preview, download, create, upload, and delete
for instance-scoped files stored on the local filesystem.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

# Security: blocked path segments
_BLOCKED_SEGMENTS = frozenset(
    {
        "credentials",
        "node_modules",
        ".env",
        "temp",
        "__pycache__",
        ".git",
        ".svn",
        ".hg",
    }
)

# Max file size for text preview (1 MB)
MAX_PREVIEW_BYTES = 1_048_576

# Default root directory name within instance storage
_DEFAULT_ROOT = "workspace"


@dataclass(frozen=True)
class FileEntry:
    """Flat representation of a single file/folder."""

    key: str
    name: str
    type: str  # "file" or "folder"
    size: int | None
    mime_type: str | None
    modified_at: str  # ISO 8601


@dataclass(frozen=True)
class FileTreeNode:
    """Recursive tree node for directory listing."""

    key: str
    name: str
    type: str
    size: int | None
    mime_type: str | None
    modified_at: str
    children: list[FileTreeNode] | None = None


class InstanceFileService:
    """Manages files within instance-scoped directories."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(
            base_dir
            or os.environ.get(
                "INSTANCE_FILES_BASE_DIR",
                "/tmp/memstack/instance_files",
            )
        )

    def _instance_root(self, instance_id: str) -> Path:
        """Get the root directory for a specific instance.

        Returns the resolved (real) path to avoid symlink mismatches
        (e.g. /tmp -> /private/tmp on macOS).
        """
        return (self._base_dir / instance_id / _DEFAULT_ROOT).resolve()

    def _validate_path(self, path: str) -> None:
        """Validate path to prevent traversal attacks."""
        parts = PurePosixPath(path).parts
        for part in parts:
            if part == "..":
                raise ValueError("Path traversal not allowed")
            if part.lower() in _BLOCKED_SEGMENTS:
                raise ValueError(f"Access to '{part}' is not allowed")

    def _resolve_safe(self, instance_id: str, relative_path: str) -> Path:
        """Resolve relative path within instance root safely."""
        self._validate_path(relative_path)
        root = self._instance_root(instance_id)
        resolved = (root / relative_path).resolve()
        # Ensure resolved path is under root
        if not str(resolved).startswith(str(root.resolve())):
            raise ValueError("Path traversal not allowed")
        return resolved

    async def list_tree(
        self,
        instance_id: str,
        path: str = "",
    ) -> list[FileTreeNode]:
        """List directory contents as a recursive tree."""
        root = self._instance_root(instance_id)
        root.mkdir(parents=True, exist_ok=True)

        if path:
            target = self._resolve_safe(instance_id, path)
        else:
            target = root

        if not target.exists():
            return []

        return self._build_tree(root, target)

    def _build_tree(
        self,
        root: Path,
        directory: Path,
    ) -> list[FileTreeNode]:
        """Recursively build the file tree."""
        nodes: list[FileTreeNode] = []
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda e: (not e.is_dir(), e.name.lower()),
            )
        except PermissionError:
            return nodes

        for entry in entries:
            # Skip hidden files/blocked segments
            if entry.name.startswith(".") and entry.name not in (".openclaw",):
                continue
            if entry.name.lower() in _BLOCKED_SEGMENTS:
                continue

            relative = entry.relative_to(root)
            key = str(PurePosixPath(relative))
            stat = entry.stat()
            modified_at = datetime.fromtimestamp(
                stat.st_mtime,
                tz=UTC,
            ).isoformat()

            if entry.is_dir():
                children = self._build_tree(root, entry)
                nodes.append(
                    FileTreeNode(
                        key=key,
                        name=entry.name,
                        type="folder",
                        size=None,
                        mime_type=None,
                        modified_at=modified_at,
                        children=children,
                    )
                )
            else:
                mime = mimetypes.guess_type(entry.name)[0]
                nodes.append(
                    FileTreeNode(
                        key=key,
                        name=entry.name,
                        type="file",
                        size=stat.st_size,
                        mime_type=mime,
                        modified_at=modified_at,
                        children=None,
                    )
                )
        return nodes

    async def read_content(
        self,
        instance_id: str,
        file_path: str,
    ) -> str:
        """Read text content of a file (capped at MAX_PREVIEW_BYTES)."""
        resolved = self._resolve_safe(instance_id, file_path)
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        size = resolved.stat().st_size
        if size > MAX_PREVIEW_BYTES:
            raise ValueError(f"File too large for preview ({size} bytes, max {MAX_PREVIEW_BYTES})")

        return resolved.read_text(encoding="utf-8", errors="replace")

    async def read_bytes(
        self,
        instance_id: str,
        file_path: str,
    ) -> tuple[bytes, str, str]:
        """Read raw bytes for download.

        Returns:
            Tuple of (content, filename, mime_type).
        """
        resolved = self._resolve_safe(instance_id, file_path)
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        return resolved.read_bytes(), resolved.name, mime

    async def create(
        self,
        instance_id: str,
        path: str,
        file_type: str,
    ) -> FileTreeNode:
        """Create a new file or folder."""
        resolved = self._resolve_safe(instance_id, path)

        if resolved.exists():
            raise FileExistsError(f"Already exists: {path}")

        if file_type == "folder":
            resolved.mkdir(parents=True, exist_ok=False)
        else:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.touch()

        root = self._instance_root(instance_id)
        relative = resolved.relative_to(root)
        stat = resolved.stat()
        modified_at = datetime.fromtimestamp(
            stat.st_mtime,
            tz=UTC,
        ).isoformat()

        return FileTreeNode(
            key=str(PurePosixPath(relative)),
            name=resolved.name,
            type=file_type,
            size=0 if file_type == "file" else None,
            mime_type=None,
            modified_at=modified_at,
        )

    async def delete(
        self,
        instance_id: str,
        file_path: str,
    ) -> None:
        """Delete a file or folder."""
        resolved = self._resolve_safe(instance_id, file_path)
        if not resolved.exists():
            raise FileNotFoundError(f"Not found: {file_path}")

        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()

    async def upload(
        self,
        instance_id: str,
        directory: str,
        filename: str,
        content: bytes,
    ) -> FileTreeNode:
        """Upload a file to the specified directory."""
        if directory:
            target_dir = self._resolve_safe(instance_id, directory)
        else:
            target_dir = self._instance_root(instance_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Validate filename
        self._validate_path(filename)
        file_path = target_dir / filename
        file_path.write_bytes(content)

        root = self._instance_root(instance_id)
        relative = file_path.relative_to(root)
        stat = file_path.stat()
        mime = mimetypes.guess_type(filename)[0]
        modified_at = datetime.fromtimestamp(
            stat.st_mtime,
            tz=UTC,
        ).isoformat()

        return FileTreeNode(
            key=str(PurePosixPath(relative)),
            name=filename,
            type="file",
            size=stat.st_size,
            mime_type=mime,
            modified_at=modified_at,
        )
