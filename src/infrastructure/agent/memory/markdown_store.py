"""Markdown-based file memory store for lightweight persistence.

Provides a simple, file-based alternative to the Neo4j graph-based memory
system. Each memory entry is stored as a markdown file with YAML frontmatter
containing metadata. Suitable for local development, small deployments, or
projects that do not require graph-based memory.

File structure per memory::

    {base_dir}/{project_id}/{conversation_id}/{timestamp}_{short_hash}.md

Markdown file format::

    ---
    project_id: {project_id}
    conversation_id: {conversation_id}
    created_at: {iso_timestamp}
    metadata: {json_metadata}
    ---

    {content}
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryEntry:
    """Immutable representation of a single memory entry read from disk.

    Attributes:
        file_path: Absolute path to the markdown file on disk.
        project_id: Project scope identifier.
        conversation_id: Originating conversation identifier.
        content: The body content of the memory (everything after frontmatter).
        metadata: Arbitrary key-value metadata stored in frontmatter.
        created_at: Timestamp when the memory was originally captured.
    """

    file_path: str
    project_id: str
    conversation_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class MarkdownMemoryStore:
    """File-based memory store using markdown files with YAML frontmatter.

    Stores each memory as an individual ``.md`` file organised by project
    and conversation. Retrieval is done via simple keyword matching against
    file contents -- no external search engine required.

    Args:
        base_dir: Root directory for storing markdown memory files.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir).resolve()
        logger.info(f"MarkdownMemoryStore initialized (base_dir={self._base_dir})")

    async def capture(
        self,
        project_id: str,
        conversation_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Write memory content to a markdown file.

        Creates the necessary directory structure and writes the content
        as a markdown file with YAML frontmatter containing metadata.

        Args:
            project_id: Project scope identifier.
            conversation_id: Originating conversation identifier.
            content: The memory content to persist.
            metadata: Optional key-value metadata to embed in frontmatter.

        Returns:
            Absolute file path of the newly created markdown file.
        """
        now = datetime.now(tz=UTC)
        short_hash = hashlib.sha256(content.encode()).hexdigest()[:8]
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")

        file_name = f"{timestamp_str}_{short_hash}.md"
        dir_path = self._base_dir / project_id / conversation_id
        file_path = dir_path / file_name

        md_content = self._build_markdown(
            project_id=project_id,
            conversation_id=conversation_id,
            content=content,
            metadata=metadata or {},
            created_at=now,
        )

        await asyncio.to_thread(self._write_file, dir_path, file_path, md_content)
        logger.info(f"Memory captured: {file_path}")
        return str(file_path)

    async def recall(
        self,
        project_id: str,
        query: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Search markdown files for matching content using keyword search.

        Performs a case-insensitive substring search across all memory files
        for the given project. Results are returned in reverse chronological
        order (newest first), capped at *limit*.

        Args:
            project_id: Project scope to search within.
            query: Search query string for case-insensitive substring matching.
            limit: Maximum number of results to return.

        Returns:
            List of matching :class:`MemoryEntry` instances, newest first.
        """
        project_dir = self._base_dir / project_id
        if not project_dir.exists():
            return []

        entries = await asyncio.to_thread(self._scan_and_filter, project_dir, query)
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    async def list_entries(self, project_id: str) -> list[MemoryEntry]:
        """List all memory entries for a project.

        Returns all memory files under the project directory, sorted in
        reverse chronological order (newest first).

        Args:
            project_id: Project scope to list entries for.

        Returns:
            List of all :class:`MemoryEntry` instances for the project.
        """
        project_dir = self._base_dir / project_id
        if not project_dir.exists():
            return []

        entries = await asyncio.to_thread(self._scan_all, project_dir)
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    async def delete(self, file_path: str) -> bool:
        """Delete a memory file from disk.

        Args:
            file_path: Absolute path to the markdown file to delete.

        Returns:
            ``True`` if the file was successfully deleted,
            ``False`` if the file was not found or deletion failed.
        """
        try:
            target = Path(file_path)
            if not target.exists():
                logger.debug(f"Memory file not found for deletion: {file_path}")
                return False
            await asyncio.to_thread(target.unlink)
            logger.info(f"Memory deleted: {file_path}")
            return True
        except FileNotFoundError:
            logger.debug(f"Memory file not found for deletion: {file_path}")
            return False
        except Exception as e:
            logger.warning(f"Failed to delete memory file {file_path}: {e}")
            return False

    @staticmethod
    def _build_markdown(
        project_id: str,
        conversation_id: str,
        content: str,
        metadata: dict[str, Any],
        created_at: datetime,
    ) -> str:
        """Build a markdown string with YAML frontmatter.

        The frontmatter uses simple string formatting rather than a YAML
        library so that no external dependency is required.
        """
        iso_ts = created_at.isoformat()
        meta_json = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        return (
            f"---\n"
            f"project_id: {project_id}\n"
            f"conversation_id: {conversation_id}\n"
            f"created_at: {iso_ts}\n"
            f"metadata: {meta_json}\n"
            f"---\n"
            f"\n"
            f"{content}\n"
        )

    @staticmethod
    def _write_file(dir_path: Path, file_path: Path, content: str) -> None:
        """Create directories and write file content (blocking I/O)."""
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _parse_markdown(file_path: Path) -> MemoryEntry | None:
        """Parse a markdown file with YAML frontmatter into a MemoryEntry.

        Uses simple string splitting rather than a YAML library to avoid
        adding external dependencies. Returns ``None`` if parsing fails.
        """
        try:
            raw = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.debug(f"Failed to read memory file {file_path}: {e}")
            return None

        if not raw.startswith("---\n"):
            return None

        parts = raw.split("---\n", 2)
        if len(parts) < 3:
            return None

        frontmatter_text = parts[1]
        body = parts[2].strip()

        fm: dict[str, str] = {}
        for line in frontmatter_text.strip().splitlines():
            colon_idx = line.find(":")
            if colon_idx == -1:
                continue
            key = line[:colon_idx].strip()
            value = line[colon_idx + 1 :].strip()
            fm[key] = value

        project_id = fm.get("project_id", "")
        conversation_id = fm.get("conversation_id", "")
        created_at_str = fm.get("created_at", "")
        metadata_str = fm.get("metadata", "{}")

        created_at = datetime.now(tz=UTC)
        if created_at_str:
            with contextlib.suppress(ValueError):
                created_at = datetime.fromisoformat(created_at_str)

        metadata: dict[str, Any] = {}
        try:
            parsed = json.loads(metadata_str)
            if isinstance(parsed, dict):
                metadata = parsed
        except (json.JSONDecodeError, TypeError):
            pass

        return MemoryEntry(
            file_path=str(file_path),
            project_id=project_id,
            conversation_id=conversation_id,
            content=body,
            metadata=metadata,
            created_at=created_at,
        )

    @classmethod
    def _scan_all(cls, project_dir: Path) -> list[MemoryEntry]:
        """Scan all markdown files under a project directory (blocking I/O)."""
        entries: list[MemoryEntry] = []
        try:
            for md_file in project_dir.rglob("*.md"):
                entry = cls._parse_markdown(md_file)
                if entry is not None:
                    entries.append(entry)
        except FileNotFoundError:
            logger.debug(f"Project directory vanished during scan: {project_dir}")
        except Exception as e:
            logger.warning(f"Error scanning project directory {project_dir}: {e}")
        return entries

    @classmethod
    def _scan_and_filter(cls, project_dir: Path, query: str) -> list[MemoryEntry]:
        """Scan markdown files and filter by case-insensitive keyword match.

        Searches both the body content and the metadata for the query string.
        """
        query_lower = query.lower()
        entries: list[MemoryEntry] = []
        try:
            for md_file in project_dir.rglob("*.md"):
                entry = cls._parse_markdown(md_file)
                if entry is None:
                    continue
                # Case-insensitive substring search in content
                if query_lower in entry.content.lower():
                    entries.append(entry)
                    continue
                # Also search in metadata values
                meta_str = json.dumps(entry.metadata, ensure_ascii=False).lower()
                if query_lower in meta_str:
                    entries.append(entry)
        except FileNotFoundError:
            logger.debug(f"Project directory vanished during search: {project_dir}")
        except Exception as e:
            logger.warning(f"Error searching project directory {project_dir}: {e}")
        return entries
