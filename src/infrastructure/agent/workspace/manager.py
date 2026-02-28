"""Workspace file manager for agent persona/soul/identity system.

Loads bootstrap files from .memstack/workspace/ directory in the sandbox.
Implements truncation, caching, and template seeding inspired by OpenClaw's
workspace.ts bootstrap system.

Key responsibilities:
- Load workspace files (SOUL.md, IDENTITY.md, USER.md, HEARTBEAT.md)
- Truncate large files with head/tail preservation
- Cache loaded content with inode-based invalidation
- Seed default templates when workspace files are missing
"""

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from src.infrastructure.agent.prompts.persona import (
    AgentPersona,
    PersonaField,
    PersonaSource,
)

logger = logging.getLogger(__name__)


# --- Constants (ported from OpenClaw bootstrap.ts / workspace.ts) ---

# Per-file character limit for workspace bootstrap files
DEFAULT_BOOTSTRAP_MAX_CHARS: int = 20_000
# Total character budget across all workspace files
DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS: int = 150_000
# Head ratio for truncation (keep first 70%)
BOOTSTRAP_HEAD_RATIO: float = 0.7
# Tail ratio for truncation (keep last 20%)
BOOTSTRAP_TAIL_RATIO: float = 0.2

# Bootstrap filenames loaded from .memstack/workspace/
WORKSPACE_FILENAMES: tuple[str, ...] = (
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "AGENTS.md",
    "TOOLS.md",
)

# Minimal allowlist for subagent/cron sessions (skip HEARTBEAT)
SUBAGENT_ALLOWLIST: frozenset[str] = frozenset({"SOUL.md", "IDENTITY.md", "USER.md"})


@dataclass(frozen=True)
class TruncationResult:
    """Result of truncating a workspace file.

    Attributes:
        content: The (possibly truncated) content.
        truncated: Whether the content was truncated.
        original_length: Original character count before truncation.
    """

    content: str
    truncated: bool
    original_length: int


@dataclass
class WorkspaceFiles:
    """Loaded workspace bootstrap files.

    Attributes:
        soul_text: Content of SOUL.md (agent personality/soul).
        identity_text: Content of IDENTITY.md (agent identity definition).
        user_profile: Content of USER.md (user profile/preferences).
        heartbeat_text: Content of HEARTBEAT.md (heartbeat instructions).
        agents_text: Content of AGENTS.md (agent configuration).
        tools_text: Content of TOOLS.md (tool configuration).
        load_errors: Errors encountered during loading.
    """

    soul_text: str | None = None
    identity_text: str | None = None
    user_profile: str | None = None
    heartbeat_text: str | None = None
    agents_text: str | None = None
    tools_text: str | None = None
    load_errors: list[str] = field(default_factory=list)

    @property
    def has_persona(self) -> bool:
        """Check if any persona/soul files were loaded."""
        return bool(self.soul_text or self.identity_text or self.user_profile or self.agents_text or self.tools_text)


def trim_bootstrap_content(
    content: str,
    filename: str,
    max_chars: int = DEFAULT_BOOTSTRAP_MAX_CHARS,
) -> TruncationResult:
    """Truncate workspace file content preserving head and tail.

    Ported from OpenClaw bootstrap.ts trimBootstrapContent().
    Keeps the first 70% and last 20% of the content, inserting a truncation
    marker in the middle.

    Args:
        content: Raw file content.
        filename: Name of the file (for the truncation marker).
        max_chars: Maximum allowed characters.

    Returns:
        TruncationResult with the processed content.
    """
    trimmed = content.rstrip()
    original_length = len(trimmed)

    if original_length <= max_chars:
        return TruncationResult(
            content=trimmed,
            truncated=False,
            original_length=original_length,
        )

    head_chars = math.floor(max_chars * BOOTSTRAP_HEAD_RATIO)
    tail_chars = math.floor(max_chars * BOOTSTRAP_TAIL_RATIO)
    head = trimmed[:head_chars]
    tail = trimmed[-tail_chars:] if tail_chars > 0 else ""

    marker = (
        f"\n[...truncated, read {filename} for full content...]\n"
        f"...(truncated {filename}: kept {head_chars}+{tail_chars} "
        f"chars of {original_length})...\n"
    )

    return TruncationResult(
        content=head + marker + tail,
        truncated=True,
        original_length=original_length,
    )


class WorkspaceManager:
    """Manages loading of workspace bootstrap files from .memstack/workspace/.

    Follows the scanner -> parser -> loader pipeline pattern used by
    FileSystemSubAgentLoader. Files are read from the sandbox filesystem
    at /workspace/.memstack/workspace/ (never from host).

    Features:
    - Loads SOUL.md, IDENTITY.md, USER.md, HEARTBEAT.md
    - Truncates oversized files with head/tail preservation
    - Caches loaded content with stat-based invalidation
    - Seeds default templates when files are missing

    Example:
        manager = WorkspaceManager(
            workspace_dir=Path("/workspace/.memstack/workspace"),
        )
        files = await manager.load_all()
        if files.has_persona:
            print(f"Soul: {files.soul_text[:100]}")
    """

    def __init__(
        self,
        workspace_dir: Path | None = None,
        tenant_workspace_dir: Path | None = None,
        max_chars_per_file: int = DEFAULT_BOOTSTRAP_MAX_CHARS,
        max_chars_total: int = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
        templates_dir: Path | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize WorkspaceManager.

        Args:
            workspace_dir: Path to .memstack/workspace/ in the sandbox (project-level).
                Defaults to /workspace/.memstack/workspace.
            tenant_workspace_dir: Path to tenant-level workspace directory.
                When set, files not found at project level fall back here
                before falling back to system templates.
            max_chars_per_file: Per-file character limit for truncation.
            max_chars_total: Total character budget across all files.
            templates_dir: Directory containing default template files.
                Defaults to prompts/workspace/ relative to this module.
            enabled: Whether workspace loading is enabled.
        """
        self._workspace_dir = workspace_dir or Path("/workspace/.memstack/workspace")
        self._tenant_workspace_dir = tenant_workspace_dir
        self._max_chars_per_file = max_chars_per_file
        self._max_chars_total = max_chars_total
        self._templates_dir = templates_dir or (
            Path(__file__).parent.parent / "prompts" / "workspace"
        )
        self._enabled = enabled

        # Cache: filename -> (content, mtime_ns)
        self._cache: dict[str, tuple[str, int]] = {}
        self._cache_valid = False

    async def load_all(
        self,
        force_reload: bool = False,
        subagent_mode: bool = False,
    ) -> WorkspaceFiles:
        """Load all workspace bootstrap files.

        Args:
            force_reload: Force reload even if cached.
            subagent_mode: If True, only load files in SUBAGENT_ALLOWLIST.

        Returns:
            WorkspaceFiles with loaded content and any errors.
        """
        if not self._enabled:
            return WorkspaceFiles()

        if self._cache_valid and not force_reload:
            return self._build_workspace_files_from_cache(subagent_mode)

        result = WorkspaceFiles()
        total_chars = 0
        filenames = (
            tuple(f for f in WORKSPACE_FILENAMES if f in SUBAGENT_ALLOWLIST)
            if subagent_mode
            else WORKSPACE_FILENAMES
        )

        for filename in filenames:
            if total_chars >= self._max_chars_total:
                logger.warning(
                    "Workspace total char budget exhausted at %d chars, skipping remaining files",
                    total_chars,
                )
                break

            remaining_budget = self._max_chars_total - total_chars
            per_file_limit = min(self._max_chars_per_file, remaining_budget)

            content = self._load_file(filename, per_file_limit)
            if content is not None:
                total_chars += len(content)
                self._set_workspace_field(result, filename, content)

        self._cache_valid = True
        if total_chars > 0:
            logger.info(
                "Loaded workspace files: %d total chars from %s",
                total_chars,
                self._workspace_dir,
            )

        return result

    async def build_persona(
        self,
        force_reload: bool = False,
        subagent_mode: bool = False,
    ) -> AgentPersona:
        """Build a first-class AgentPersona from workspace files.

        Loads workspace files via ``load_all()`` and wraps each into a
        ``PersonaField`` with source/truncation metadata.

        Args:
            force_reload: Force reload even if cached.
            subagent_mode: If True, only load SUBAGENT_ALLOWLIST files.

        Returns:
            AgentPersona with metadata for each loaded field.
        """
        files = await self.load_all(
            force_reload=force_reload,
            subagent_mode=subagent_mode,
        )
        return AgentPersona(
            soul=self._to_persona_field(
                files.soul_text,
                "SOUL.md",
            ),
            identity=self._to_persona_field(
                files.identity_text,
                "IDENTITY.md",
            ),
            user_profile=self._to_persona_field(
                files.user_profile,
                "USER.md",
            ),
            agents=self._to_persona_field(
                files.agents_text,
                "AGENTS.md",
            ),
            tools=self._to_persona_field(
                files.tools_text,
                "TOOLS.md",
            ),
        )

    def _to_persona_field(
        self,
        content: str | None,
        filename: str,
    ) -> PersonaField:
        """Convert raw content to a PersonaField with metadata.

        Args:
            content: The loaded content (or None if missing).
            filename: The source filename.

        Returns:
            PersonaField with source and truncation tracking.
        """
        if content is None:
            return PersonaField.empty(filename)

        # Determine source: project workspace > tenant workspace > template
        workspace_path = self._workspace_dir / filename
        if workspace_path.exists():
            source = PersonaSource.WORKSPACE
        elif (
            self._tenant_workspace_dir
            and (self._tenant_workspace_dir / filename).exists()
        ):
            source = PersonaSource.TENANT
        else:
            source = PersonaSource.TEMPLATE

        # Check if this file was truncated by inspecting the cache
        cached = self._cache.get(filename)
        raw_chars = len(content)
        is_truncated = False
        if cached is not None:
            # Use trim_bootstrap_content logic: if content contains truncation
            # marker, it was truncated
            is_truncated = "[...truncated, read" in content

        return PersonaField(
            content=content,
            source=source,
            raw_chars=raw_chars,
            injected_chars=len(content),
            is_truncated=is_truncated,
            filename=filename,
        )

    def _load_file(self, filename: str, max_chars: int) -> str | None:
        """Load a single workspace file with caching and truncation.

        Args:
            filename: Name of the file to load.
            max_chars: Character limit for this file.

        Returns:
            File content (possibly truncated) or None if not found.
        """
        file_path = self._workspace_dir / filename

        if not file_path.exists():
            # Try tenant-level workspace as fallback
            return self._load_tenant_or_template(filename, max_chars)

        try:
            stat = file_path.stat()
            mtime_ns = stat.st_mtime_ns

            # Check cache by mtime
            cached = self._cache.get(filename)
            if cached is not None and cached[1] == mtime_ns:
                return cached[0]

            raw_content = file_path.read_text(encoding="utf-8")
            truncation = trim_bootstrap_content(raw_content, filename, max_chars)

            if truncation.truncated:
                logger.debug(
                    "Truncated %s: %d -> %d chars",
                    filename,
                    truncation.original_length,
                    len(truncation.content),
                )

            self._cache[filename] = (truncation.content, mtime_ns)
            return truncation.content

        except PermissionError:
            logger.warning("Permission denied reading workspace file: %s", file_path)
            return None
        except OSError as e:
            logger.warning("Failed to read workspace file %s: %s", file_path, e)
            return None

    def _load_tenant_or_template(self, filename: str, max_chars: int) -> str | None:
        """Try loading from tenant workspace, then fall back to template.

        Implements the middle tier of the 3-tier resolution:
        project-level (workspace_dir) > tenant-level > system template.

        Args:
            filename: Name of the file to load.
            max_chars: Character limit for this file.

        Returns:
            File content (possibly truncated) or None if not found.
        """
        if self._tenant_workspace_dir:
            tenant_path = self._tenant_workspace_dir / filename
            if tenant_path.exists():
                try:
                    stat = tenant_path.stat()
                    mtime_ns = stat.st_mtime_ns
                    cache_key = f"tenant:{filename}"

                    # Check cache by mtime
                    cached = self._cache.get(cache_key)
                    if cached is not None and cached[1] == mtime_ns:
                        # Store under the filename key too for _to_persona_field
                        self._cache[filename] = cached
                        return cached[0]

                    raw_content = tenant_path.read_text(encoding="utf-8")
                    truncation = trim_bootstrap_content(raw_content, filename, max_chars)

                    if truncation.truncated:
                        logger.debug(
                            "Truncated tenant %s: %d -> %d chars",
                            filename,
                            truncation.original_length,
                            len(truncation.content),
                        )

                    self._cache[cache_key] = (truncation.content, mtime_ns)
                    self._cache[filename] = (truncation.content, mtime_ns)
                    return truncation.content

                except PermissionError:
                    logger.warning("Permission denied reading tenant file: %s", tenant_path)
                except OSError as e:
                    logger.warning("Failed to read tenant file %s: %s", tenant_path, e)

        return self._load_template(filename, max_chars)

    def _load_template(self, filename: str, max_chars: int) -> str | None:
        """Load a default template file as fallback.

        Args:
            filename: Name of the template file.
            max_chars: Character limit.

        Returns:
            Template content or None if template not found.
        """
        template_path = self._templates_dir / filename
        if not template_path.exists():
            return None

        try:
            raw_content = template_path.read_text(encoding="utf-8")
            truncation = trim_bootstrap_content(raw_content, filename, max_chars)
            # Cache templates with mtime 0 (they don't change at runtime)
            self._cache[filename] = (truncation.content, 0)
            return truncation.content
        except OSError as e:
            logger.debug("Failed to load template %s: %s", template_path, e)
            return None

    def _build_workspace_files_from_cache(self, subagent_mode: bool) -> WorkspaceFiles:
        """Build WorkspaceFiles from cached content.

        Args:
            subagent_mode: If True, only include SUBAGENT_ALLOWLIST files.

        Returns:
            WorkspaceFiles populated from cache.
        """
        result = WorkspaceFiles()
        filenames = (
            tuple(f for f in WORKSPACE_FILENAMES if f in SUBAGENT_ALLOWLIST)
            if subagent_mode
            else WORKSPACE_FILENAMES
        )

        for filename in filenames:
            cached = self._cache.get(filename)
            if cached is not None:
                self._set_workspace_field(result, filename, cached[0])

        return result

    @staticmethod
    def _set_workspace_field(result: WorkspaceFiles, filename: str, content: str) -> None:
        """Set the appropriate field on WorkspaceFiles based on filename.

        Args:
            result: WorkspaceFiles instance to update.
            filename: The bootstrap filename.
            content: The file content to set.
        """
        field_map: dict[str, str] = {
            "SOUL.md": "soul_text",
            "IDENTITY.md": "identity_text",
            "USER.md": "user_profile",
            "HEARTBEAT.md": "heartbeat_text",
            "AGENTS.md": "agents_text",
            "TOOLS.md": "tools_text",
        }
        attr = field_map.get(filename)
        if attr is not None:
            setattr(result, attr, content)

    def invalidate_cache(self) -> None:
        """Invalidate the cache, forcing reload on next access."""
        self._cache.clear()
        self._cache_valid = False
