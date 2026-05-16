"""Workspace manifest for tracking file state across sandbox lifecycle.

The manifest is a JSON file (workspace-manifest.json) stored inside the
.memstack directory of each project workspace. It records:
- Which files exist in the workspace
- Their sizes, checksums, and timestamps
- Whether each file has been synced to S3 backup
- Runtime dependencies installed in the sandbox

This enables workspace recovery after sandbox container destruction and
recreation, and bidirectional sync with S3 for disaster recovery.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Manifest filename relative to workspace root
MANIFEST_FILENAME = ".memstack/workspace-manifest.json"
MANIFEST_VERSION = 1


@dataclass
class FileEntry:
    """Tracks the state of a single file in the workspace.

    Attributes:
        relative_path: Path relative to workspace root.
        size: File size in bytes.
        sha256: SHA-256 hex digest of file content.
        created_at: ISO 8601 timestamp when the file was first tracked.
        synced_to_s3: Whether the file has been uploaded to S3 backup.
        s3_key: S3 object key if synced.
    """

    relative_path: str
    size: int
    sha256: str
    created_at: str
    synced_to_s3: bool = False
    s3_key: str | None = None

    def mark_synced(self, s3_key: str) -> None:
        """Mark this file as synced to S3."""
        self.synced_to_s3 = True
        self.s3_key = s3_key


@dataclass
class WorkspaceManifest:
    """Tracks workspace file state for sync and recovery.

    Attributes:
        version: Manifest format version.
        project_id: Owning project identifier.
        tenant_id: Owning tenant identifier.
        created_at: ISO 8601 timestamp when manifest was created.
        last_sandbox_id: ID of the last sandbox container that used this workspace.
        files: Map of relative_path -> FileEntry for tracked files.
        runtime_dependencies: List of pip packages installed in the sandbox.
        last_sync_at: ISO 8601 timestamp of the last S3 sync.
    """

    version: int = MANIFEST_VERSION
    project_id: str = ""
    tenant_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_sandbox_id: str | None = None
    last_sandbox_state: str | None = None
    files: dict[str, FileEntry] = field(default_factory=dict)
    runtime_dependencies: list[str] = field(default_factory=list)
    last_sync_at: str | None = None

    # --- Persistence ---

    def save(self, workspace_path: str | Path) -> None:
        """Write the manifest to disk.

        Args:
            workspace_path: Absolute path to the workspace root directory.
        """
        manifest_path = Path(workspace_path) / MANIFEST_FILENAME
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        data = self._to_dict()
        _ = manifest_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.debug("Saved workspace manifest to %s", manifest_path)

    @classmethod
    def load(cls, workspace_path: str | Path) -> WorkspaceManifest | None:
        """Load a manifest from disk.

        Args:
            workspace_path: Absolute path to the workspace root directory.

        Returns:
            A WorkspaceManifest instance, or None if the manifest file does not exist.
        """
        manifest_path = Path(workspace_path) / MANIFEST_FILENAME
        if not manifest_path.exists():
            return None

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return cls._from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning(
                "Failed to parse workspace manifest at %s, treating as absent",
                manifest_path,
            )
            return None

    @classmethod
    def create(
        cls,
        _workspace_path: str | Path,
        project_id: str,
        tenant_id: str = "",
    ) -> WorkspaceManifest:
        """Create a new manifest for a workspace.

        Does NOT write to disk -- call save() after creation.

        Args:
            workspace_path: Absolute path to the workspace root directory.
            project_id: Owning project identifier.
            tenant_id: Owning tenant identifier.

        Returns:
            A new WorkspaceManifest instance.
        """
        return cls(
            project_id=project_id,
            tenant_id=tenant_id,
        )

    # --- Scanning ---

    @classmethod
    def scan(
        cls,
        workspace_path: str | Path,
        project_id: str = "",
        tenant_id: str = "",
    ) -> WorkspaceManifest:
        """Scan a workspace directory and create a manifest reflecting current state.

        Loads existing manifest if present (to preserve sync state), then
        updates it with the current files on disk.

        Args:
            workspace_path: Absolute path to the workspace root directory.
            project_id: Owning project identifier (used if creating new manifest).
            tenant_id: Owning tenant identifier (used if creating new manifest).

        Returns:
            An updated WorkspaceManifest.
        """
        existing = cls.load(workspace_path)
        manifest = existing or cls.create(workspace_path, project_id, tenant_id)

        ws = Path(workspace_path)
        if not ws.exists():
            return manifest

        current_files: dict[str, FileEntry] = {}
        for root, _dirs, filenames in os.walk(ws):
            for filename in filenames:
                abs_path = Path(root) / filename
                rel_path = str(abs_path.relative_to(ws))

                # Skip the manifest file itself
                if rel_path == MANIFEST_FILENAME:
                    continue
                # Skip hidden dirs like __pycache__
                if "/__pycache__/" in rel_path or rel_path.startswith("__pycache__/"):
                    continue

                try:
                    stat = abs_path.stat()
                    sha256 = _compute_sha256(abs_path)
                except OSError:
                    logger.debug("Skipping inaccessible file: %s", abs_path)
                    continue

                # Preserve sync state from existing manifest
                old_entry = manifest.files.get(rel_path)
                if old_entry is not None and old_entry.sha256 == sha256:
                    current_files[rel_path] = old_entry
                else:
                    current_files[rel_path] = FileEntry(
                        relative_path=rel_path,
                        size=stat.st_size,
                        sha256=sha256,
                        created_at=datetime.now(UTC).isoformat(),
                    )

        manifest.files = current_files
        return manifest

    # --- Queries ---

    def unsynced_files(self) -> list[FileEntry]:
        """Return files that have not been synced to S3."""
        return [f for f in self.files.values() if not f.synced_to_s3]

    def files_missing_on_disk(self, workspace_path: str | Path) -> list[FileEntry]:
        """Return manifest entries whose files are missing from disk.

        Args:
            workspace_path: Absolute path to the workspace root directory.
        """
        ws = Path(workspace_path)
        return [entry for entry in self.files.values() if not (ws / entry.relative_path).exists()]

    def update_sandbox_id(self, sandbox_id: str) -> None:
        """Record the sandbox ID that is using this workspace."""
        self.last_sandbox_id = sandbox_id

    def update_sandbox_state(self, state: str) -> None:
        """Record the last known sandbox state for recovery."""
        self.last_sandbox_state = state

    def add_runtime_dependency(self, package: str) -> None:
        """Add a runtime dependency to the manifest (deduplicating)."""
        if package not in self.runtime_dependencies:
            self.runtime_dependencies.append(package)

    # --- Serialization ---

    def _to_dict(self) -> dict[str, Any]:
        """Serialize the manifest to a JSON-compatible dict."""
        return {
            "version": self.version,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at,
            "last_sandbox_id": self.last_sandbox_id,
            "last_sandbox_state": self.last_sandbox_state,
            "files": {
                path: {
                    "size": entry.size,
                    "sha256": entry.sha256,
                    "created_at": entry.created_at,
                    "synced_to_s3": entry.synced_to_s3,
                    "s3_key": entry.s3_key,
                }
                for path, entry in self.files.items()
            },
            "runtime_dependencies": self.runtime_dependencies,
            "last_sync_at": self.last_sync_at,
        }

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> WorkspaceManifest:
        """Deserialize a manifest from a dict."""
        files: dict[str, FileEntry] = {}
        for path, entry_data in data.get("files", {}).items():
            files[path] = FileEntry(
                relative_path=path,
                size=entry_data["size"],
                sha256=entry_data["sha256"],
                created_at=entry_data["created_at"],
                synced_to_s3=entry_data.get("synced_to_s3", False),
                s3_key=entry_data.get("s3_key"),
            )

        return cls(
            version=data.get("version", MANIFEST_VERSION),
            project_id=data.get("project_id", ""),
            tenant_id=data.get("tenant_id", ""),
            created_at=data.get("created_at", datetime.now(UTC).isoformat()),
            last_sandbox_id=data.get("last_sandbox_id"),
            last_sandbox_state=data.get("last_sandbox_state"),
            files=files,
            runtime_dependencies=data.get("runtime_dependencies", []),
            last_sync_at=data.get("last_sync_at"),
        )


def _compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file.

    Reads the file in chunks to handle large files efficiently.

    Args:
        path: Absolute path to the file.

    Returns:
        Hex digest string.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
